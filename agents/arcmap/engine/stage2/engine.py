# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
import os, re, csv, json, time, uuid, shutil, hashlib, math
try:
    from difflib import SequenceMatcher
except Exception:
    SequenceMatcher = None

FILE_EXTS = set(['.shp','.lyr','.tif','.tiff','.img','.sid','.jp2','.jpg','.jpeg','.png','.asc','.bil','.bmp','.gif','.ecw','.ntf','.dem','.csv','.txt','.dwg','.dxf','.dgn','.kml','.kmz'])
DANGEROUS_GP = set(['delete','truncate','compact','compress','unregister','reconcile','post','migrate','rename','remove','clearworkspacecache'])

try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)

DEFAULT_EXPORT_FORMATS = ['PDF', 'PNG']
DEFAULT_EXPORT_DPI = 400
DEFAULT_OUTPUT_FOLDER = 'Hasil Peta'


def _arcpy(required=True):
    try:
        import arcpy
        return arcpy
    except Exception:
        if required: raise RuntimeError('ArcPy tidak tersedia. Jalankan engine di ArcMap 10.6.1 / Python 2.7.')
        return None

def ensure_dir(p):
    if p and not os.path.isdir(p): os.makedirs(p)
    return p

def read_json(p):
    with open(p,'rb') as f: raw=f.read()
    if not isinstance(raw,str): raw=raw.decode('utf-8')
    return json.loads(raw)

def write_json(p,obj):
    ensure_dir(os.path.dirname(p))
    data=json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)
    if not isinstance(data,bytes): data=data.encode('utf-8')
    with open(p,'wb') as f: f.write(data)
    return p

def norm(v):
    s=os.path.splitext(os.path.basename(str(v)))[0].lower()
    return re.sub(r'[^0-9a-z]+','',s)

def slug(v):
    s=re.sub(r'[^0-9a-zA-Z_\-]+','_',str(v).strip())
    return re.sub(r'_+','_',s).strip('_') or 'PETA_A4'

def safe_filename(v):
    s=str(v or '').strip()
    s=re.sub(r'[<>:"/\\|?*]+','_',s)
    s=re.sub(r'\s+',' ',s).strip(' .')
    return s or 'PETA A4'

def production_name(company_name,map_type):
    company=safe_filename(company_name).strip()
    kind=safe_filename(map_type).strip()
    if not company or not kind:
        raise ValueError('company_name dan map_type wajib untuk penamaan produksi standar')
    return safe_filename('PETA A4 %s - %s' % (company, kind))

def production_output_dir(output_dir):
    root=os.path.abspath(output_dir)
    if os.path.basename(os.path.normpath(root)).lower() == DEFAULT_OUTPUT_FOLDER.lower():
        return root
    return os.path.join(root, DEFAULT_OUTPUT_FOLDER)

def sha1(path):
    h=hashlib.sha1()
    with open(path,'rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

# ---------- DATA DISCOVERY ----------
def _csv_fields(path):
    try:
        raw=open(path,'rb').read(65536)
        try: text=raw.decode('utf-8-sig')
        except Exception: text=raw.decode('latin-1')
        first=text.splitlines()[0]
        try: dialect=csv.Sniffer().sniff(first)
        except Exception: dialect=csv.excel
        return next(csv.reader([first],dialect))
    except Exception: return []

def discover_data(data_root,max_items=10000):
    data_root=os.path.abspath(data_root)
    if not os.path.isdir(data_root): raise ValueError('Folder data tidak ditemukan: '+data_root)
    arcpy=_arcpy(False); items=[]; warnings=[]; seen=set()
    if arcpy:
        try:
            for dirpath,dirnames,filenames in arcpy.da.Walk(data_root,datatype=['FeatureClass','RasterDataset','Table','CadDrawingDataset','Tin']):
                for name in filenames:
                    path=os.path.join(dirpath,name)
                    try:
                        d=arcpy.Describe(path)
                        row={'path':path,'relative':os.path.relpath(path,data_root),'name':name,'norm':norm(name),'kind':getattr(d,'dataType',''),'shape_type':getattr(d,'shapeType',None),'spatial_reference':getattr(getattr(d,'spatialReference',None),'name',None),'source':'arcpy.da.Walk'}
                        items.append(row); seen.add(os.path.normcase(path))
                        if len(items)>=max_items: return {'root':data_root,'items':items,'warnings':['max_items reached'],'count':len(items)}
                    except Exception as e: warnings.append('Describe gagal %s: %s'%(path,e))
        except Exception as e: warnings.append('arcpy.da.Walk fallback: %s'%e)
    for base,dirs,files in os.walk(data_root):
        dirs[:]=[d for d in dirs if not d.lower().endswith('.gdb')]
        for name in files:
            ext=os.path.splitext(name)[1].lower()
            if ext not in FILE_EXTS: continue
            path=os.path.join(base,name)
            if os.path.normcase(path) in seen: continue
            row={'path':path,'relative':os.path.relpath(path,data_root),'name':name,'norm':norm(name),'kind':ext.lstrip('.').upper(),'shape_type':None,'spatial_reference':None,'source':'filesystem'}
            if ext in ('.csv','.txt'):
                fs=_csv_fields(path); row['fields']=fs
                n=[norm(x) for x in fs]; row['xy_hint']={'x_fields':[fs[i] for i,x in enumerate(n) if x in ('x','lon','long','longitude','easting','bujur')],'y_fields':[fs[i] for i,x in enumerate(n) if x in ('y','lat','latitude','northing','lintang')]}
            items.append(row)
            if len(items)>=max_items: warnings.append('max_items reached'); break
    items.sort(key=lambda x:(x.get('kind',''),x.get('relative','').lower()))
    return {'root':data_root,'items':items,'warnings':warnings,'count':len(items)}

# ---------- SLOT MATCHING ----------
def _score(slot,item):
    target=norm(slot.get('dataset') or slot.get('name') or slot.get('layer') or '')
    cand=item.get('norm') or norm(item.get('name',''))
    if not target or not cand: return 0.0
    if target==cand: return 1.0
    if cand in [norm(x) for x in slot.get('aliases',[])]: return 0.99
    for pat in slot.get('patterns',[]):
        try:
            if re.search(pat,item.get('relative',''),re.I): return 0.97
        except Exception: pass
    if target in cand or cand in target: return 0.90
    return (SequenceMatcher(None,target,cand).ratio()*0.85) if SequenceMatcher else 0.0

def match_slots(slots,discovered,min_score=0.62):
    items=discovered.get('items',discovered); used=set(); matches=[]; missing=[]
    for slot in slots:
        ranked=[]
        for i,item in enumerate(items):
            if i in used and not slot.get('allow_reuse',False): continue
            sk=(slot.get('kind') or '').lower(); ik=(item.get('kind') or '').lower()
            if sk and sk not in ik: continue
            ss=(slot.get('shape_type') or '').lower(); ishp=(item.get('shape_type') or '').lower()
            if ss and ishp and ss!=ishp: continue
            s=_score(slot,item)
            if s>=min_score: ranked.append((s,i,item))
        ranked.sort(key=lambda x:(-x[0],x[2].get('relative','')))
        if ranked:
            s,i,item=ranked[0]; used.add(i); matches.append({'slot':slot,'item':item,'score':round(s,4)})
        elif slot.get('required',True): missing.append(slot)
    return {'matches':matches,'missing':missing,'matched_count':len(matches)}

# ---------- MXD / LAYERS ----------
def open_mxd(path): return _arcpy().mapping.MapDocument(path)
def get_df(mxd,name=''):
    dfs=_arcpy().mapping.ListDataFrames(mxd)
    if not dfs: raise RuntimeError('MXD tidak memiliki data frame')
    if not name: return dfs[0]
    for d in dfs:
        if d.name==name: return d
    raise KeyError('Data frame tidak ditemukan: '+name)

def find_layer(mxd,df,name):
    arcpy=_arcpy(); exact=[x for x in arcpy.mapping.ListLayers(mxd,'',df) if x.name==name or getattr(x,'longName','')==name]
    if exact: return exact[0]
    x=arcpy.mapping.ListLayers(mxd,name,df)
    if x: return x[0]
    raise KeyError('Layer tidak ditemukan: '+name)

def _layer_from_dataset(path,temp_name):
    arcpy=_arcpy(); ext=os.path.splitext(path)[1].lower()
    if ext=='.lyr': return arcpy.mapping.Layer(path)
    d=arcpy.Describe(path); dt=getattr(d,'dataType','').lower()
    if 'raster' in dt: r=arcpy.MakeRasterLayer_management(path,temp_name)
    elif 'feature' in dt or ext=='.shp': r=arcpy.MakeFeatureLayer_management(path,temp_name)
    else: raise ValueError('Dataset tidak dapat ditambahkan sebagai layer: %s (%s)'%(path,dt))
    out=r.getOutput(0)
    # ArcGIS Desktop 10.6 may return an arcpy._mapping.Layer object directly.
    # Wrapping that object again with arcpy.mapping.Layer raises TypeError.
    try:
        if isinstance(out, arcpy.mapping.Layer):
            return out
    except TypeError:
        # Some ArcPy builds expose Layer as a factory rather than a type.
        if out.__class__.__module__.startswith('arcpy') and out.__class__.__name__=='Layer':
            return out
    except Exception:
        pass
    return arcpy.mapping.Layer(out)

def add_dataset(mxd,df,path,name=None,position='BOTTOM'):
    arcpy=_arcpy(); lyr=_layer_from_dataset(path,'zagent_'+str(abs(hash(path)))[:9])
    if name: lyr.name=name
    arcpy.mapping.AddLayer(df,lyr,position)
    out=arcpy.mapping.ListLayers(mxd,lyr.name,df)
    return out[-1] if out else lyr

def workspace_parts(path):
    low=path.lower(); sep=os.sep
    if '.gdb'+sep in low or low.endswith('.gdb'):
        idx=low.index('.gdb')+4; return path[:idx],'FILEGDB_WORKSPACE',path[idx+1:] if len(path)>idx else ''
    ext=os.path.splitext(path)[1].lower()
    if ext=='.shp': return os.path.dirname(path),'SHAPEFILE_WORKSPACE',os.path.splitext(os.path.basename(path))[0]
    if ext in ('.tif','.tiff','.img','.sid','.jp2','.jpg','.jpeg','.png','.asc','.bil','.bmp','.gif','.ecw','.ntf','.dem'):
        return os.path.dirname(path),'RASTER_WORKSPACE',os.path.basename(path)
    return os.path.dirname(path),'NONE',os.path.basename(path)

def replace_source(mxd,df,layer_name,path):
    lyr=find_layer(mxd,df,layer_name); ws,wt,ds=workspace_parts(path); lyr.replaceDataSource(ws,wt,ds,True); return lyr

def apply_order(mxd,df,names):
    arcpy=_arcpy(); resolved=[find_layer(mxd,df,n) for n in names]
    for i in range(len(resolved)-1,0,-1): arcpy.mapping.MoveLayer(df,resolved[i-1],resolved[i],'AFTER')
    return [x.name for x in resolved]

# ---------- SYMBOLOGY / LABELS ----------
def apply_style(mxd,df,layer_name,style_lyr):
    arcpy=_arcpy(); target=find_layer(mxd,df,layer_name); source=arcpy.mapping.Layer(style_lyr); arcpy.mapping.UpdateLayer(df,target,source,True); return True

def configure_layer(mxd,df,layer_name,cfg):
    lyr=find_layer(mxd,df,layer_name)
    lyr.visible=bool(cfg.get('visible',True))
    if 'transparency' in cfg: lyr.transparency=int(cfg['transparency'])
    if 'min_scale' in cfg: lyr.minScale=float(cfg['min_scale'])
    if 'max_scale' in cfg: lyr.maxScale=float(cfg['max_scale'])
    if cfg.get('style_lyr'): apply_style(mxd,df,layer_name,cfg['style_lyr'])
    if cfg.get('unique_values'):
        u=cfg['unique_values']; s=lyr.symbology
        if s.symbologyType!='UNIQUE_VALUES': raise RuntimeError('Renderer bukan UNIQUE_VALUES: '+layer_name)
        s.valueField=u['field']; s.addAllValues(); s.showOtherValues=bool(u.get('show_other',True)); lyr.symbology=s
    if cfg.get('graduated'):
        g=cfg['graduated']; s=lyr.symbology
        if s.symbologyType not in ('GRADUATED_COLORS','GRADUATED_SYMBOLS'): raise RuntimeError('Renderer bukan graduated: '+layer_name)
        s.valueField=g['field']; s.classBreakValues=list(g['breaks']);
        if g.get('labels'): s.classBreakLabels=list(g['labels'])
        lyr.symbology=s
    if cfg.get('labels'):
        lcfg=cfg['labels']
        if not lyr.supports('LABELCLASSES'): raise RuntimeError('Layer tidak mendukung label: '+layer_name)
        classes=lyr.labelClasses; cc=lcfg.get('classes') or [lcfg]
        for i,c in enumerate(cc):
            if i>=len(classes): break
            lc=classes[i]
            if 'expression' in c: lc.expression=c['expression']
            if 'sql_query' in c: lc.SQLQuery=c['sql_query']
            if 'show_class_labels' in c: lc.showClassLabels=bool(c['show_class_labels'])
        lyr.showLabels=bool(lcfg.get('show',True))
    return lyr

# ---------- LEGEND ----------
def get_legend(mxd,name=''):
    a=_arcpy().mapping.ListLayoutElements(mxd,'LEGEND_ELEMENT',name or '')
    if not a: raise KeyError('LegendElement tidak ditemukan: '+(name or '<first>'))
    exact=[x for x in a if not name or x.name==name]
    return exact[0] if exact else a[0]

def legend_manifest(mxd,name=''):
    l=get_legend(mxd,name)
    return {'name':l.name,'title':l.title,'auto_add':l.autoAdd,'x':l.elementPositionX,'y':l.elementPositionY,'width':l.elementWidth,'height':l.elementHeight,'overflow':bool(l.isOverflowing),'items':[x.name for x in l.listLegendItemLayers()]}

def rebuild_legend(mxd,df,cfg):
    arcpy=_arcpy(); l=get_legend(mxd,cfg.get('name','')); l.autoAdd=bool(cfg.get('auto_add',True)); l.title=cfg.get('title') or ' '
    for attr,key in [('elementPositionX','x'),('elementPositionY','y'),('elementWidth','width'),('elementHeight','height')]:
        if key in cfg: setattr(l,attr,float(cfg[key]))
    wanted=cfg.get('items')
    if wanted:
        ws=set(wanted)
        for lyr in list(l.listLegendItemLayers())[::-1]:
            if lyr.name not in ws:
                try: l.removeItem(lyr)
                except Exception: pass
    style=None
    if cfg.get('style_file') and cfg.get('style_name'):
        x=arcpy.mapping.ListStyleItems(cfg['style_file'],'LEGEND_ITEM',cfg['style_name'])
        if not x: raise KeyError('LEGEND_ITEM style tidak ditemukan')
        style=x[0]
    for lyr in list(l.listLegendItemLayers()):
        if wanted and lyr.name not in wanted: continue
        try: l.updateItem(lyr,style,True,bool(cfg.get('use_visible_extent',False)),bool(cfg.get('show_feature_count',False)),False)
        except Exception:
            try:
                if style: l.updateItem(lyr,style)
            except Exception: pass
    cols=max(1,int(cfg.get('columns',1))); l.adjustColumnCount(cols)
    max_cols=max(cols,int(cfg.get('max_columns',4)))
    while l.isOverflowing and cols<max_cols:
        cols+=1; l.adjustColumnCount(cols)
    if l.isOverflowing and cfg.get('allow_expand_height',True):
        step=float(cfg.get('expand_step',0.3)); limit=float(cfg.get('max_height',l.elementHeight+5))
        while l.isOverflowing and l.elementHeight<limit: l.elementHeight+=step
    out=legend_manifest(mxd,cfg.get('name','')); out['columns']=cols; return out

# ---------- LAYOUT ----------
def find_element(mxd,name,etype=None):
    a=_arcpy().mapping.ListLayoutElements(mxd,etype or '',name)
    for x in a:
        if x.name==name: return x
    if a: return a[0]
    raise KeyError('Layout element tidak ditemukan: '+name)

def _element_by_index(mxd,index,etype=None):
    # Index follows the global layout manifest order, matching arcmap_get_layout_manifest.
    items=_arcpy().mapping.ListLayoutElements(mxd)
    idx=int(index)
    if idx<0 or idx>=len(items): raise IndexError('Layout element index di luar jangkauan: %s'%idx)
    e=items[idx]
    if etype and getattr(e,'type',None)!=etype:
        raise TypeError('Layout element index %s bertipe %s, bukan %s'%(idx,getattr(e,'type',None),etype))
    return e

def _select_layout_element(mxd,row,default_type=None,default_name=None):
    if isinstance(row,dict) and row.get('index') is not None:
        return _element_by_index(mxd,row.get('index'),row.get('type') or default_type)
    name=(row or {}).get('name') if isinstance(row,dict) else None
    return find_element(mxd,name or default_name,row.get('type') if isinstance(row,dict) else default_type)

def _set_box(e,row):
    for attr,key in [('elementPositionX','x'),('elementPositionY','y'),('elementWidth','width'),('elementHeight','height')]:
        if key in row and hasattr(e,attr): setattr(e,attr,float(row[key]))

def apply_layout(mxd,cfg):
    for name,row in (cfg.get('text') or {}).items():
        e=_select_layout_element(mxd,row,'TEXT_ELEMENT',name)
        e.text=row.get('value') or row.get('text') or ' '
        if 'font_size' in row and hasattr(e,'fontSize'): e.fontSize=float(row['font_size'])
        _set_box(e,row)
    for row in (cfg.get('text_items') or []):
        e=_select_layout_element(mxd,row,'TEXT_ELEMENT',row.get('name'))
        e.text=row.get('value') or row.get('text') or ' '
        if 'font_size' in row and hasattr(e,'fontSize'): e.fontSize=float(row['font_size'])
        _set_box(e,row)
    for name,row in (cfg.get('pictures') or {}).items():
        e=_select_layout_element(mxd,row,'PICTURE_ELEMENT',name)
        if row.get('source'): e.sourceImage=row['source']
        _set_box(e,row)
    for row in (cfg.get('picture_items') or []):
        e=_select_layout_element(mxd,row,'PICTURE_ELEMENT',row.get('name'))
        if row.get('source'): e.sourceImage=row['source']
        _set_box(e,row)
    for name,row in (cfg.get('elements') or {}).items():
        e=_select_layout_element(mxd,row,row.get('type'),name)
        _set_box(e,row)
    for row in (cfg.get('element_items') or []):
        e=_select_layout_element(mxd,row,row.get('type'),row.get('name'))
        _set_box(e,row)
    return True

def layout_manifest(mxd):
    rows=[]
    for e in _arcpy().mapping.ListLayoutElements(mxd):
        r={'name':e.name,'type':e.type}
        for attr,key in [('elementPositionX','x'),('elementPositionY','y'),('elementWidth','width'),('elementHeight','height')]:
            if hasattr(e,attr): r[key]=getattr(e,attr)
        if hasattr(e,'text'): r['text']=e.text
        if hasattr(e,'fontSize'): r['font_size']=e.fontSize
        rows.append(r)
    return rows

# ---------- EXTENT / SCALE ----------
def nice_scale(s):
    if s<=0: return s
    exp=10**int(math.floor(math.log10(s))); n=s/exp
    for b in [1,2,2.5,5,10]:
        if n<=b: return b*exp
    return 10*exp

def configure_extent(mxd,df,cfg):
    if cfg.get('layer'):
        lyr=find_layer(mxd,df,cfg['layer']); df.extent=lyr.getExtent(True); df.scale=df.scale*float(cfg.get('factor',1.08))
    if cfg.get('scale'): df.scale=float(cfg['scale'])
    elif cfg.get('nice_scale'): df.scale=nice_scale(df.scale)
    if 'rotation' in cfg: df.rotation=float(cfg['rotation'])
    return {'scale':df.scale,'rotation':getattr(df,'rotation',0)}

# ---------- CHECKPOINT / QA ----------
def checkpoint(mxd_path,snapshot_root,job_id,label='baseline'):
    d=ensure_dir(os.path.join(snapshot_root,job_id)); token=time.strftime('%Y%m%d_%H%M%S')+'_'+slug(label); dst=os.path.join(d,token+'.mxd'); shutil.copy2(mxd_path,dst)
    meta={'token':token,'mxd':dst,'sha1':sha1(dst),'created':time.strftime('%Y-%m-%dT%H:%M:%S')}; write_json(os.path.join(d,token+'.json'),meta); return meta

def restore_checkpoint(checkpoint_mxd,target_mxd):
    if not os.path.isfile(checkpoint_mxd): raise ValueError('Checkpoint tidak ditemukan: '+checkpoint_mxd)
    tmp=target_mxd+'.restore_tmp'; shutil.copy2(checkpoint_mxd,tmp)
    if os.path.exists(target_mxd): os.remove(target_mxd)
    os.rename(tmp,target_mxd); return {'restored':target_mxd,'from':checkpoint_mxd}


def list_checkpoints(snapshot_root,job_id):
    d=os.path.join(snapshot_root,job_id)
    if not os.path.isdir(d): return []
    out=[]
    for name in sorted(os.listdir(d)):
        if name.lower().endswith('.mxd'):
            path=os.path.join(d,name)
            out.append({'name':name,'path':path,'sha1':sha1(path)})
    return out

def a4_check(mxd):
    p=mxd.pageSize; w=float(p.width); h=float(p.height)
    cm=(abs(w-21)<=0.25 and abs(h-29.7)<=0.25) or (abs(h-21)<=0.25 and abs(w-29.7)<=0.25)
    inch=(abs(w-8.2677)<=0.1 and abs(h-11.6929)<=0.1) or (abs(h-8.2677)<=0.1 and abs(w-11.6929)<=0.1)
    mm=(abs(w-210)<=2.5 and abs(h-297)<=2.5) or (abs(h-210)<=2.5 and abs(w-297)<=2.5)
    return {'ok':bool(cm or inch or mm),'width':w,'height':h}

def qa(mxd,recipe,profile=None):
    arcpy=_arcpy(); errors=[]; warnings=[]; checks={}
    broken=arcpy.mapping.ListBrokenDataSources(mxd); checks['broken_data_sources']=[getattr(x,'name',str(x)) for x in broken]
    if broken: errors.append('Ada %d broken data source'%len(broken))
    checks['a4']=a4_check(mxd)
    if recipe.get('require_a4',True) and not checks['a4']['ok']: errors.append('Template/page bukan A4')
    lm=layout_manifest(mxd); names=set([x['name'] for x in lm]); req=(profile or {}).get('required_layout_elements',recipe.get('required_layout_elements',[])); miss=[x for x in req if x not in names]; checks['missing_layout_elements']=miss
    if miss: errors.append('Layout element wajib hilang: '+', '.join(miss))
    if recipe.get('legend') or (profile or {}).get('legend'):
        try:
            lc={}; lc.update((profile or {}).get('legend') or {}); lc.update(recipe.get('legend') or {}); lg=legend_manifest(mxd,lc.get('name','')); checks['legend']=lg
            if lg['overflow']: errors.append('Legenda overflow')
        except Exception as e: errors.append('Legenda gagal dibaca: '+str(e))
    empty=[]
    for df in arcpy.mapping.ListDataFrames(mxd):
        for lyr in arcpy.mapping.ListLayers(mxd,'',df):
            try:
                if lyr.isFeatureLayer and lyr.visible and int(arcpy.GetCount_management(lyr).getOutput(0))==0: empty.append(lyr.name)
            except Exception: pass
    checks['visible_empty_layers']=empty
    if empty: warnings.append('Layer terlihat tetapi kosong: '+', '.join(empty))
    return {'ok':not errors,'errors':errors,'warnings':warnings,'checks':checks}

# ---------- EXPORT ----------
def export_map(mxd,output_dir,base_name,cfg=None,allow_custom_export=False):
    arcpy=_arcpy(); ensure_dir(output_dir); cfg=cfg or {}; out={}
    if allow_custom_export:
        dpi=int(cfg.get('resolution',DEFAULT_EXPORT_DPI))
        fmts=[x.upper() for x in cfg.get('formats',DEFAULT_EXPORT_FORMATS)]
    else:
        # Default produksi user: hanya PDF + PNG, selalu 400 DPI.
        dpi=DEFAULT_EXPORT_DPI
        fmts=list(DEFAULT_EXPORT_FORMATS)
    funcs={'PDF':arcpy.mapping.ExportToPDF,'PNG':arcpy.mapping.ExportToPNG,'JPEG':arcpy.mapping.ExportToJPEG,'JPG':arcpy.mapping.ExportToJPEG,'TIFF':arcpy.mapping.ExportToTIFF,'TIF':arcpy.mapping.ExportToTIFF,'EPS':arcpy.mapping.ExportToEPS,'SVG':arcpy.mapping.ExportToSVG,'AI':arcpy.mapping.ExportToAI,'EMF':arcpy.mapping.ExportToEMF}
    extmap={'JPEG':'jpg','JPG':'jpg','TIFF':'tif','TIF':'tif'}
    for f in fmts:
        if f not in funcs: raise ValueError('Format export tidak didukung: '+f)
        path=os.path.join(output_dir,safe_filename(base_name)+'.'+extmap.get(f,f.lower())); fn=funcs[f]
        if f in ('PDF','EPS','SVG','AI'): fn(mxd,path,resolution=dpi)
        elif f in ('JPEG','JPG'): fn(mxd,path,resolution=dpi,jpeg_quality=int(cfg.get('jpeg_quality',92)))
        else: fn(mxd,path,resolution=dpi)
        out[f]=path
    return out

# ---------- GENERIC GEOPROCESSING ----------
def run_gp(tool,args=None,kwargs=None,allow_destructive=False):
    low=tool.lower()
    if not allow_destructive and any(x in low for x in DANGEROUS_GP): raise RuntimeError('GP diblokir guard: '+tool)
    obj=_arcpy()
    for part in tool.replace('arcpy.','').split('.'): obj=getattr(obj,part)
    r=obj(*(args or []),**(kwargs or {})); outs=[]
    try:
        for i in range(r.outputCount): outs.append(r.getOutput(i))
    except Exception:
        try: outs=[r.getOutput(0)]
        except Exception: pass
    return {'tool':tool,'outputs':outs,'status':getattr(r,'status',None)}

# ---------- PRODUCTION ----------
def _load(v):
    return read_json(v) if isinstance(v,string_types) and os.path.isfile(v) else v


def _format_layout_value(value,context):
    if not isinstance(value,string_types): return value
    try: return value.format(**context)
    except Exception: return value

def _render_layout_tokens(layout,context):
    for section in ('text','text_items'):
        obj=layout.get(section)
        rows=obj.values() if isinstance(obj,dict) else (obj if isinstance(obj,list) else [])
        for row in rows:
            if not isinstance(row,dict): continue
            if 'value' in row: row['value']=_format_layout_value(row['value'],context)
            if 'text' in row: row['text']=_format_layout_value(row['text'],context)
    return layout

def build_a4(template_mxd,data_root,output_dir,recipe,profile=None,base_name=None,
             snapshot_root=None,save_mxd=True,company_name=None,map_type=None):
    recipe=_load(recipe) or {}; profile=_load(profile) or {}
    company_name=company_name or recipe.get('company_name') or ''
    map_type=map_type or recipe.get('map_type') or ''
    if company_name and map_type:
        name=production_name(company_name,map_type)
    else:
        name=safe_filename(base_name or recipe.get('output_name') or recipe.get('name') or 'PETA A4')

    # Semua hasil produksi masuk folder Hasil Peta.
    output_dir=production_output_dir(output_dir)
    job_id=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    ensure_dir(output_dir)
    job_dir=ensure_dir(os.path.join(output_dir,'_jobs',job_id))
    snapshot_root=snapshot_root or os.path.join(output_dir,'_snapshots')
    if not os.path.isfile(template_mxd): raise ValueError('Template MXD tidak ditemukan: '+template_mxd)

    working=os.path.join(job_dir,name+'.mxd')
    shutil.copy2(template_mxd,working)
    cp=checkpoint(working,snapshot_root,job_id,'template_baseline')
    disc=discover_data(data_root,int(recipe.get('max_discovery_items',10000)))
    write_json(os.path.join(job_dir,'discovery.json'),disc)
    matches=match_slots(recipe.get('layers',[]),disc,float(recipe.get('min_match_score',0.62)))
    write_json(os.path.join(job_dir,'matches.json'),matches)
    if matches['missing'] and recipe.get('fail_on_missing_required',True):
        raise RuntimeError('Dataset wajib tidak ditemukan: '+', '.join([x.get('name','?') for x in matches['missing']]))

    mxd=open_mxd(working)
    try:
        df=get_df(mxd,recipe.get('data_frame',''))
        for mr in matches['matches']:
            slot,item=mr['slot'],mr['item']
            lname=slot.get('layer') or slot.get('name') or item['name']
            mode=slot.get('mode','replace_or_add')
            existing=None
            try: existing=find_layer(mxd,df,lname)
            except Exception: pass
            if existing and mode in ('replace','replace_or_add'):
                try: lyr=replace_source(mxd,df,lname,item['path'])
                except Exception:
                    if mode=='replace': raise
                    lyr=add_dataset(mxd,df,item['path'],lname,slot.get('position','BOTTOM'))
            elif existing and mode=='skip_if_exists':
                lyr=existing
            else:
                lyr=add_dataset(mxd,df,item['path'],lname,slot.get('position','BOTTOM'))
            configure_layer(mxd,df,lyr.name,slot)

        if recipe.get('layer_order'): apply_order(mxd,df,recipe['layer_order'])
        for gp in recipe.get('geoprocessing',[]):
            run_gp(gp['tool'],gp.get('args'),gp.get('kwargs'),bool(gp.get('allow_destructive',False)))
        if recipe.get('extent'): configure_extent(mxd,df,recipe['extent'])

        layout={}
        layout.update(profile.get('layout') or {})
        for k,v in (recipe.get('layout') or {}).items():
            if isinstance(v,dict) and isinstance(layout.get(k),dict):
                merged=dict(layout.get(k) or {}); merged.update(v); layout[k]=merged
            else:
                layout[k]=v
        context={'company_name':company_name,'map_type':map_type,'map_name':name}
        _render_layout_tokens(layout,context)
        if layout: apply_layout(mxd,layout)

        leg={}; leg.update(profile.get('legend') or {}); leg.update(recipe.get('legend') or {})
        if leg: rebuild_legend(mxd,df,leg)

        # Hanya working copy yang disimpan; template sumber tidak disentuh.
        mxd.save()
        q=qa(mxd,recipe,profile)
        write_json(os.path.join(job_dir,'qa.json'),q)
        if not q['ok'] and recipe.get('fail_on_qa',True):
            raise RuntimeError('QA gagal: '+'; '.join(q['errors']))

        export_cfg=recipe.get('export',{}) or {}
        custom_export=bool(recipe.get('allow_custom_export',False))
        ex=export_map(mxd,output_dir,name,export_cfg,custom_export)
        final_mxd=os.path.join(output_dir,name+'.mxd')
        if save_mxd: mxd.saveACopy(final_mxd)
        report={
            'ok':True,'job_id':job_id,'name':name,'template':template_mxd,
            'working_mxd':working,'final_mxd':final_mxd if save_mxd else None,
            'baseline_checkpoint':cp['mxd'],'exports':ex,'output_dir':output_dir,
            'export_dpi':int(export_cfg.get('resolution',DEFAULT_EXPORT_DPI)) if custom_export else DEFAULT_EXPORT_DPI,
            'export_formats':[x.upper() for x in export_cfg.get('formats',DEFAULT_EXPORT_FORMATS)] if custom_export else list(DEFAULT_EXPORT_FORMATS),
            'discovery_count':disc['count'],'matches':matches,'qa':q
        }
        write_json(os.path.join(output_dir,name+'.__report__.json'),report)
        return report
    finally:
        try: del mxd
        except Exception: pass


def batch_build(job_file_or_obj):
    cfg=_load(job_file_or_obj); results=[]
    for j in cfg.get('jobs',[]):
        try:
            results.append(build_a4(
                j['template_mxd'],j['data_root'],j['output_dir'],j['recipe'],
                j.get('profile'),j.get('base_name'),j.get('snapshot_root'),
                j.get('save_mxd',True),j.get('company_name'),j.get('map_type')
            ))
        except Exception as e:
            results.append({'ok':False,'error':str(e),'job':j})
            if cfg.get('stop_on_error',False): break
    return {'ok':all(x.get('ok') for x in results),'results':results}
