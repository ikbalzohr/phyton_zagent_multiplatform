COMPOSITE_EFFECTS={
    "arcmap_stage2_batch_build":{"hidden_effects":{"working_mxd_save","staging_export","optional_final_copy"},"direct_final_forbidden":True},
    "arcmap_stage2_build_a4":{"hidden_effects":{"working_mxd_save","staging_export","optional_final_copy"},"direct_final_forbidden":True},
    "arcmap_stage3_build_blank_a4":{"hidden_effects":{"document_mutation","save","export"},"direct_final_forbidden":True},
    "arcmap_stage3_build_no_data_a4":{"hidden_effects":{"document_mutation","save","export"},"direct_final_forbidden":True},
}
def composite_effect(name):
    return COMPOSITE_EFFECTS.get(name,{"hidden_effects":set(),"direct_final_forbidden":False})
def allowed_for_orchestrated_final(name):
    return not composite_effect(name)["direct_final_forbidden"]
