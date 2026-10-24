"""Cross-profile batch is disabled until both resources have independent bindings.

Do not revive the old Engine.bind(session, seed_profile) implementation: an
existing session ignores the seed and could silently copy inside its active root.
"""


def copy_batch_between_profiles(source_profile: str, paths: list[str],
                                destination_profile: str, destination_dir: str,
                                overwrite: bool = False,
                                flatten: bool = False,
                                preserve_relative_path: bool = True):
    raise PermissionError('CROSS_PROFILE_COPY_DISABLED')
