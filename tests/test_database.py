from __future__ import annotations

from storage.database import Database


def test_database_seeds_expanded_builtin_vibration_presets():
    database = Database(":memory:")
    database.initialize()

    presets = database.get_vibration_presets()
    builtin_names = {preset["name"] for preset in presets if preset["is_builtin"] == 1}

    assert len(builtin_names) == 145
    assert "ν(C=O) –COCl acid halide" in builtin_names
    assert "ν(C=O) anhydride asym." in builtin_names
    assert "ν(N₃) –N₃ azide" in builtin_names
    assert "ν(N=C=O) –N=C=O isocyanate" in builtin_names
    assert "ν(N=C=N) carbodiimide" in builtin_names
    assert "ν(N=C=S) –N=C=S isothiocyanate" in builtin_names
    assert "ν(C=C=O) ketene" in builtin_names
    assert "ν(CO) R–O–R aliph. ether" in builtin_names
    assert "ν(CO) Ar–O–R aryl ether" in builtin_names
    assert "ν(CO) CH₂=CH–O– vinyl ether" in builtin_names
    assert "ν(S=O) sulfoxide" in builtin_names
    assert "νas(SO₂) sulfone" in builtin_names
    assert "νas(SO₃) sulfate" in builtin_names
    assert "νas(SO₃) sulfonate" in builtin_names
    assert "νs(SO₂) sulfonyl chloride" in builtin_names
    assert "ν(SH) thiol" in builtin_names

    database.close()
