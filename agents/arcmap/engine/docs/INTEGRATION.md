# Integrasi ke baseline 91 tools

Paket ini tidak mengganti source lama. `install_stage2.py`:
1. mencari `arcmap_bridge/ArcMapAgent.pyt`;
2. membuat file `.bak` sebelum mengubah entrypoint;
3. menambahkan hook untuk memasukkan action Stage2 ke registry action existing;
4. mencari entry MCP (`server.py`, `main.py`, `app.py`, atau `mcp_server.py`);
5. menambahkan 7 tool MCP Stage2 melalui object `.tool` dan memakai transport bridge existing.

Action bridge baru:
- stage2_discover_data
- stage2_preview_match
- stage2_validate_template
- stage2_build_a4
- stage2_batch_build
- stage2_restore_checkpoint
- stage2_generic_gp

Tool MCP yang diharapkan setelah restart:
- arcmap_stage2_discover_data
- arcmap_stage2_preview_match
- arcmap_stage2_validate_template
- arcmap_stage2_build_a4
- arcmap_stage2_batch_build
- arcmap_stage2_restore_checkpoint
- arcmap_stage2_generic_gp

Jika registry/transport baseline Anda memakai nama yang sangat custom dan auto-detection tidak menemukannya, source Stage2 tetap aman dan baseline tetap dibackup; penyesuaian manual hanya diperlukan di fungsi `auto_install`.
