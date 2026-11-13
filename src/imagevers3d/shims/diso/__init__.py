"""
Module factice « diso » : TripoSG l'importe pour son extraction de maillage rapide (DiffDMC), une
extension CUDA à compiler. L'application utilise l'autre extraction de TripoSG (scikit-image,
`use_flash_decoder=False`), qui donne le même résultat sans compilation ; ce module n'existe que pour
que l'import réussisse.
"""


class DiffDMC:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "diso n'est pas installé (module factice). Appelle le pipeline TripoSG avec "
            "use_flash_decoder=False."
        )
