"""Recognise every IR-relevant group in a drawn structure, and its vibrations.

``perceive_motifs`` reads a molecule the way a chemist names its parts: an
ether oxygen bonded to a C=O is an *ester*, not an ether plus a ketone; an
N–C(=O)–O unit is a *carbamate*, not an amide plus an ester; a ring of four
nitrogens and a carbon is a *tetrazole*. Each recognised motif lists the
vibrations of the built-in library (by their shipped names) that it can show,
so the Vibrations panel can offer only those and the spectrum can mark where
they appear.

How the perception works
------------------------
The catalog below is ordered from the most specific motif to the most
general. Atoms written with a map number in a pattern (``[C:1]``) are the
motif's *core*; an exclusive motif is reported only where none of its core
atoms already belongs to an earlier, more specific motif, and then it claims
them. That is what keeps the C=O of an ester from also reading as a ketone and
its oxygen from reading as an ether, while a tert-butyl next to the same ester
(Boc, t-Bu ester) is still reported — substituent motifs such as methyl,
methylene, tert-butyl, methoxy or the benzene substitution pattern are
*additive*: they describe the skeleton and never claim atoms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from functools import cache
from typing import Any

from rdkit import Chem

# Families, in the order the Vibrations panel lists them.
FAMILY_CARBONYL = "Carbonyl groups"
FAMILY_NITROGEN = "Nitrogen groups"
FAMILY_OXYGEN = "Oxygen groups"
FAMILY_HETEROCYCLE = "Heteroaromatic rings"
FAMILY_AROMATIC = "Aromatic rings"
FAMILY_UNSATURATED = "Double and triple bonds"
FAMILY_SULFUR_PHOSPHORUS = "Sulfur, phosphorus, boron, silicon"
FAMILY_HALOGEN = "Halogens"
FAMILY_ALKYL = "Alkyl skeleton"
FAMILIES: tuple[str, ...] = (
    FAMILY_CARBONYL,
    FAMILY_NITROGEN,
    FAMILY_OXYGEN,
    FAMILY_HETEROCYCLE,
    FAMILY_AROMATIC,
    FAMILY_UNSATURATED,
    FAMILY_SULFUR_PHOSPHORUS,
    FAMILY_HALOGEN,
    FAMILY_ALKYL,
)


@dataclass(frozen=True)
class Motif:
    """One recognisable group and the library vibrations it can show."""

    id: str
    name: str
    family: str
    smarts: tuple[str, ...]
    vibrations: tuple[str, ...]
    #: Exclusive motifs claim their core atoms; additive ones never do.
    exclusive: bool = True
    #: For 1,2-disubstituted alkenes: "trans", "cis" or "unknown" geometry.
    geometry: str = ""


@dataclass(frozen=True)
class FoundMotif:
    """A motif found in a molecule: how often and on which atoms."""

    motif: Motif
    matches: tuple[tuple[int, ...], ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        return len(self.matches)

    @property
    def id(self) -> str:
        return self.motif.id

    @property
    def name(self) -> str:
        return self.motif.name

    @property
    def vibrations(self) -> tuple[str, ...]:
        return self.motif.vibrations


def _m(
    motif_id: str,
    name: str,
    family: str,
    smarts: str | tuple[str, ...],
    vibrations: tuple[str, ...],
    *,
    exclusive: bool = True,
    geometry: str = "",
) -> Motif:
    patterns = (smarts,) if isinstance(smarts, str) else smarts
    return Motif(motif_id, name, family, patterns, vibrations, exclusive, geometry)


# Vibration groups shared by several motifs.
_NH_STRETCH = ("ν(NH) –NH–",)
_NH2_STRETCH = ("νas(NH₂) –NH₂", "νs(NH₂) –NH₂")
_OH_STRETCH = ("ν(OH) –OH solid/liq.", "ν(OH) –OH dimer H-bond")
_AR_RING = (
    "ν(CH) Ar",
    "ν(C=C) Ar ~1600",
    "ν(C=C) Ar conj. ~1580",
    "ν(C=C) Ar ~1490",
    "Ar overtone/comb.",
)

_DISUBSTITUTED_ALKENE = "[#6][CX3H1;!a:1]=[CX3H1;!a:2][#6]"

#: The catalog, most specific first. Map numbers mark core atoms.
MOTIFS: tuple[Motif, ...] = (
    # 2-Pyridone first: its ring C=O–N would otherwise read as a tertiary amide.
    _m(
        "pyridone",
        "2-Pyridone",
        FAMILY_HETEROCYCLE,
        "[#8X1]=[#6:1]1:[#7:2]:[#6]:[#6]:[#6]:[#6]:1",
        ("ν(C=O) 2-pyridone", "ν(C–N) 2-pyridone", "δ(CH) 2-pyridone", "ν(CH) Ar"),
    ),
    # ── Carbonyl groups and their derivatives ───────────────────────────────
    _m(
        "anhydride",
        "Acid anhydride",
        FAMILY_CARBONYL,
        "[#6X3:1](=[OX1:2])[OX2:3][#6X3:4](=[OX1:5])",
        ("ν(C=O) anhydride asym.", "ν(C=O) anhydride sym.", "ν(CO–O–CO) anhydride"),
    ),
    _m(
        "acid_halide",
        "Acyl halide",
        FAMILY_CARBONYL,
        "[#6X3:1](=[OX1:2])[F,Cl,Br,I:3]",
        ("ν(C=O) –COCl acid halide", "ν(C=O) conj. –COCl acid halide"),
    ),
    _m(
        "carbonate",
        "Carbonate",
        FAMILY_CARBONYL,
        "[OX2:2][#6X3:1](=[OX1:3])[OX2:4]",
        ("ν(C=O) carbonate", "νas(O–C–O) carbonate"),
    ),
    _m(
        "carbamate",
        "Carbamate (urethane, Boc, Cbz, Fmoc)",
        FAMILY_CARBONYL,
        "[NX3:2][#6X3:1](=[OX1:3])[OX2:4][#6]",
        (
            "ν(C=O) –NH–CO–O– carbamate",
            "ν(NH) –NH–",
            "δ(NH)+ν(CN) carbamate amide II",
            "ν(C–O) carbamate",
        ),
    ),
    _m(
        "urea",
        "Urea",
        FAMILY_CARBONYL,
        "[#7X3:2][#6X3:1](=[OX1:3])[#7X3:4]",
        ("ν(C=O) urea", "ν(NH) –NH–", "νas(NH₂) –NH₂", "δ(NH)+ν(CN) urea amide II"),
    ),
    _m(
        "imide",
        "Imide",
        FAMILY_CARBONYL,
        "[#6X3:1](=[OX1:2])[#7X3:3][#6X3:4](=[OX1:5])",
        ("νas(C=O) imide", "νs(C=O) imide", "ν(NH) –NH–"),
    ),
    _m(
        "thioamide",
        "Thioamide / thiourea",
        FAMILY_CARBONYL,
        "[#6X3:1](=[SX1:2])[#7X3:3]",
        ("ν(C=S) thioamide/thiourea", "ν(NH) –NH–", "δ(NH) –NH–"),
    ),
    _m(
        "beta_lactam",
        "β-Lactam",
        FAMILY_CARBONYL,
        "[#6X3;r4:1](=[OX1:2])[#7X3;r4:3]",
        ("ν(C=O) β-lactam", "ν(NH) –NH–"),
    ),
    _m(
        "gamma_lactam",
        "γ-Lactam (2-pyrrolidone)",
        FAMILY_CARBONYL,
        "[#6X3;r5:1](=[OX1:2])[#7X3;r5:3]",
        ("ν(C=O) γ-lactam", "ν(NH) –NH–", "δ(NH)+ν(CN) amide II –CO–NH– sec."),
    ),
    _m(
        "primary_amide",
        "Primary amide –CONH₂",
        FAMILY_CARBONYL,
        "[#6,#1][#6X3:1](=[OX1:2])[NX3H2:3]",
        (
            "νas(NH₂) –CO–NH₂",
            "νs(NH₂) –CO–NH₂",
            "νas(NH₂) –CONH₂",
            "νs(NH₂) –CONH₂",
            "ν(C=O) amide I –CO–NH₂ (1670–1690)",
            "ν(C=O) amide I –CO–NH₂ (1650–1670)",
            "δ(NH₂) amide II –CO–NH₂",
            "δ(NH₂) –CO–NH₂",
            "ν(CN) amide III –CO–NH₂",
            "γ(NH₂) –CO–NH₂ amide",
        ),
    ),
    _m(
        "secondary_amide",
        "Secondary amide –CONH–",
        FAMILY_CARBONYL,
        ("[#6,#1][#6X3:1](=[OX1:2])[#7X3H1:3][#6]",),
        (
            "ν(NH) –NH–",
            "ν(C=O) amide I –CO–NH– sec.",
            "δ(NH)+ν(CN) amide II –CO–NH– sec.",
            "ν(CN) amide III –NH–CO–",
            "ω(NH) –NH–",
        ),
    ),
    _m(
        "tertiary_amide",
        "Tertiary amide –CONR₂",
        FAMILY_CARBONYL,
        "[#6,#1][#6X3:1](=[OX1:2])[#7X3H0:3]([#6])[#6]",
        ("ν(C=O) amide I –CO–NR₂ tert.",),
    ),
    _m(
        "hydrazide",
        "Hydrazide / hydroxamic acid",
        FAMILY_CARBONYL,
        "[#6X3:1](=[OX1:2])[#7X3:3][#7,#8]",
        ("ν(C=O) amide I –CO–NH– sec.", "ν(NH) –NH–", "δ(NH)+ν(CN) amide II –CO–NH– sec."),
    ),
    _m(
        "carboxylic_acid",
        "Carboxylic acid",
        FAMILY_CARBONYL,
        "[#6,#1][CX3:1](=[OX1:2])[OX2H1:3]",
        (
            "ν(OH) –OH chelate H-bond",
            "ν(OH) –COOH monomer",
            "ν(C=O) –COOH dimer",
            "ν(C=O) Ar–COOH dimer",
            "ν(C=O) –COOH monomer",
            "δ(OH)+ν(CO) –COOH dimer",
            "ν(CO) –COOH monomer",
            "δ(OH) –COOH monomer",
            "γ(OH) –COOH dimer",
        ),
    ),
    _m(
        "carboxylate",
        "Carboxylate (salt)",
        FAMILY_CARBONYL,
        "[CX3:1](=[OX1:2])[OX1-:3]",
        ("νas(COO⁻) carboxylate", "νs(COO⁻) carboxylate"),
    ),
    _m(
        "beta_lactone",
        "β-Lactone",
        FAMILY_CARBONYL,
        "[#6X3;r4:1](=[OX1:2])[OX2;r4:3]",
        ("ν(C=O) β-lactone", "νs(COC) R–CO–O–R' sat."),
    ),
    _m(
        "gamma_lactone",
        "γ-Lactone (5-ring)",
        FAMILY_CARBONYL,
        "[#6X3;r5:1](=[OX1:2])[OX2;r5:3]",
        ("ν(C=O) γ-lactone", "νs(COC) R–CO–O–R' sat."),
    ),
    _m(
        "formate",
        "Formate ester",
        FAMILY_CARBONYL,
        "[CX3H1:1](=[OX1:2])[OX2:3][#6]",
        ("ν(C=O) H–CO–O–R formate", "νs(COC) R–CO–O–R' sat."),
    ),
    _m(
        "aryl_vinyl_ester",
        "Phenyl / vinyl ester (–CO–O–Ar)",
        FAMILY_CARBONYL,
        "[#6][#6X3:1](=[OX1:2])[OX2:3][c,$(C=C)]",
        ("ν(C=O) vinyl/phenyl ester", "νs(COC) R–CO–O–R' sat."),
    ),
    _m(
        "conjugated_ester",
        "Conjugated ester (aryl / α,β-unsaturated)",
        FAMILY_CARBONYL,
        "[c,$(C=C),$(C#C)][#6X3:1](=[OX1:2])[OX2:3][#6]",
        (
            "ν(C=O) Ar–CO–O–R ester",
            "ν(C=O) –CO–O– α,β-unsat. ester",
            "ν(C–O) α,β-unsat. ester",
        ),
    ),
    _m(
        "ester",
        "Ester",
        FAMILY_CARBONYL,
        "[#6][#6X3:1](=[OX1:2])[OX2:3][#6]",
        ("ν(C=O) –CO–O– sat. ester", "νs(COC) R–CO–O–R' sat.", "2×ν(C=O) overtone"),
    ),
    _m(
        "aldehyde",
        "Aldehyde",
        FAMILY_CARBONYL,
        ("[#6][CX3H1:1]=[OX1:2]", "[CX3H2:1]=[OX1:2]"),
        (
            "ν(C=O) –CHO aldehyde",
            "ν(CH) –CHO",
            "ν(CH)+overtone –CHO",
            "δ(CH) –CHO",
            "γ(CH) –CHO",
        ),
    ),
    _m(
        "cyclobutanone",
        "Cyclobutanone",
        FAMILY_CARBONYL,
        "[#6][#6X3;r4:1](=[OX1:2])[#6]",
        ("ν(C=O) cyclobutanone",),
    ),
    _m(
        "cyclopentanone",
        "Cyclopentanone",
        FAMILY_CARBONYL,
        "[CX4][CX3;r5:1](=[OX1:2])[CX4]",
        ("ν(C=O) cyclopentanone", "δ(CH₂) adj. C=O/Ar"),
    ),
    _m(
        "conjugated_ketone",
        "Conjugated ketone (aryl / enone / quinone)",
        FAMILY_CARBONYL,
        "[c,$(C=C)][#6X3:1](=[OX1:2])[#6]",
        ("ν(C=O) ArCO– α,β-unsat. ketone", "ν(CCC) R–CO–R' ketone"),
    ),
    _m(
        "ketone",
        "Ketone",
        FAMILY_CARBONYL,
        "[#6][#6X3:1](=[OX1:2])[#6]",
        (
            "ν(C=O) R–CO–R' sat. ketone",
            "ν(CCC) R–CO–R' ketone",
            "δ(CH₂) adj. C=O/Ar",
            "2×ν(C=O) overtone",
        ),
    ),
    # ── Nitrogen groups ──────────────────────────────────────────────────────
    _m(
        "nitrate",
        "Nitrate ester –O–NO₂",
        FAMILY_NITROGEN,
        "[OX2:1][$([NX3:2](=O)=O),$([NX3+:2](=O)[O-])]",
        ("νas(NO₂) –O–NO₂ nitrate", "νs(NO₂) –O–NO₂ nitrate", "ν(N–O) –O–NO₂ nitrate"),
    ),
    _m(
        "nitro",
        "Nitro –NO₂",
        FAMILY_NITROGEN,
        "[#6][$([NX3:1](=O)=O),$([NX3+:1](=O)[O-])]",
        ("νas(NO₂) –NO₂", "νs(NO₂) –NO₂"),
    ),
    _m(
        "azide",
        "Azide –N₃",
        FAMILY_NITROGEN,
        ("[NX2:1]=[NX2+:2]=[NX1-:3]", "[NX2-:1][NX2+:2]#[NX1:3]"),
        ("ν(N₃) –N₃ azide", "νs(N₃) –N₃ azide"),
    ),
    _m(
        "isocyanate",
        "Isocyanate –N=C=O",
        FAMILY_NITROGEN,
        "[NX2:1]=[CX2:2]=[OX1:3]",
        ("ν(N=C=O) –N=C=O isocyanate", "νs(NCO) –N=C=O"),
    ),
    _m(
        "isothiocyanate",
        "Isothiocyanate –N=C=S",
        FAMILY_NITROGEN,
        "[NX2:1]=[CX2:2]=[SX1:3]",
        ("ν(N=C=S) –N=C=S isothiocyanate",),
    ),
    _m(
        "carbodiimide",
        "Carbodiimide –N=C=N–",
        FAMILY_NITROGEN,
        "[NX2:1]=[CX2:2]=[NX2:3]",
        ("ν(N=C=N) carbodiimide",),
    ),
    _m(
        "thiocyanate",
        "Thiocyanate –S–C≡N",
        FAMILY_NITROGEN,
        "[SX2:1][CX2:2]#[NX1:3]",
        ("ν(S–C≡N) –SCN thiocyanate",),
    ),
    _m(
        "nitrile",
        "Nitrile –C≡N",
        FAMILY_NITROGEN,
        "[#6,#7][CX2:1]#[NX1:2]",
        ("ν(C≡N) –C≡N",),
    ),
    _m(
        "azo",
        "Azo –N=N–",
        FAMILY_NITROGEN,
        "[#6][NX2:1]=[NX2:2][#6]",
        ("ν(N=N) azo",),
    ),
    _m(
        "n_oxide",
        "N-oxide",
        FAMILY_NITROGEN,
        "[#7+;!$([N+](=O)[O-]):1][OX1-:2]",
        ("ν(N⁺–O⁻) N-oxide",),
    ),
    _m(
        "oxime",
        "Oxime C=N–OH",
        FAMILY_NITROGEN,
        "[CX3:2]=[NX2:1][OX2H1:3]",
        ("ν(C=N) C=N–OH oxime", "ν(NO) –C=N–OH oxime", "ν(OH) –OH solid/liq."),
    ),
    _m(
        "guanidine_amidine",
        "Amidine / guanidine",
        FAMILY_NITROGEN,
        "[NX3;!$(N-[#6]=[O,S]):2][CX3;!r5;!r6:1]=[NX2:3]",
        ("ν(C=N) amidine/guanidine", "ν(NH) –NH–", "δ(NH₂) –NH₂"),
    ),
    _m(
        "imine",
        "Imine / Schiff base C=N",
        FAMILY_NITROGEN,
        "[#6][CX3;!$(C-[O,S]):1]=[NX2;!$(N-[O,N]):2]",
        ("ν(C=N) R₂C=N–R imine",),
    ),
    _m(
        "ammonium",
        "Ammonium salt –NH₃⁺ / R₃NH⁺",
        FAMILY_NITROGEN,
        "[NX4+;H1,H2,H3:1]",
        ("ν(NH) amine salt", "δ(NH₃⁺) amine salt"),
    ),
    _m(
        "aromatic_primary_amine",
        "Aromatic amine Ar–NH₂ (aniline)",
        FAMILY_NITROGEN,
        "c[NX3H2;!$(N[#6,#16,#15]=[O,S,N]):1]",
        _NH2_STRETCH + ("δ(NH₂) –NH₂", "ν(CN) Ar–NH₂ aniline", "γ(NH) –NH₂"),
    ),
    _m(
        "aromatic_secondary_amine",
        "Aromatic amine Ar–NH–R",
        FAMILY_NITROGEN,
        "c[NX3H1;!$(N[#6,#16,#15]=[O,S,N]);!$(N-[N,O]):1][#6]",
        _NH_STRETCH + ("δ(NH) –NH–", "ν(CN) Ar₂NH/Ar–NH–R", "ω(NH) –NH–"),
    ),
    _m(
        "primary_amine",
        "Primary amine –NH₂",
        FAMILY_NITROGEN,
        "[CX4][NX3H2;!$(N-[N,O]):1]",
        _NH2_STRETCH + ("δ(NH₂) –NH₂", "ν(CN) RNH₂", "γ(NH) –NH₂"),
    ),
    _m(
        "secondary_amine",
        "Secondary amine R₂NH",
        FAMILY_NITROGEN,
        "[CX4][NX3H1;!$(N[#6,#16,#15]=[O,S,N]);!$(N-[N,O]):1][CX4]",
        _NH_STRETCH + ("δ(NH) –NH–", "ν(CN) R₂NH", "ω(NH) –NH–"),
    ),
    _m(
        "tertiary_amine",
        "Tertiary amine R₃N",
        FAMILY_NITROGEN,
        "[#6][NX3H0;!$(N[#6,#16,#15]=[O,S,N]);!$(N-[N,O]);!$(N-a);!a:1]([#6])[#6]",
        ("ν(CN) tert. amine", "ν(CH) N–CH Bohlmann bands"),
    ),
    # ── Sulfur, phosphorus, boron, silicon ───────────────────────────────────
    _m(
        "sulfonyl_chloride",
        "Sulfonyl chloride –SO₂Cl",
        FAMILY_SULFUR_PHOSPHORUS,
        "[SX4:1](=[OX1:2])(=[OX1:3])[Cl:4]",
        ("νas(SO₂) sulfonyl chloride", "νs(SO₂) sulfonyl chloride"),
    ),
    _m(
        "sulfonamide",
        "Sulfonamide –SO₂N<",
        FAMILY_SULFUR_PHOSPHORUS,
        "[SX4:1](=[OX1:2])(=[OX1:3])[NX3:4]",
        ("νas(SO₂) sulfonamide", "νs(SO₂) sulfonamide", "ν(NH) sulfonamide"),
    ),
    _m(
        "sulfate",
        "Sulfate –O–SO₂–O–",
        FAMILY_SULFUR_PHOSPHORUS,
        "[OX2:1][SX4:2](=[OX1:3])(=[OX1:4])[OX2,OX1-:5]",
        ("νas(SO₃) sulfate", "νs(SO₃) sulfate"),
    ),
    _m(
        "sulfonate",
        "Sulfonate / sulfonic acid –SO₃R",
        FAMILY_SULFUR_PHOSPHORUS,
        "[#6][SX4:1](=[OX1:2])(=[OX1:3])[OX2,OX1-:4]",
        ("νas(SO₃) sulfonate", "νs(SO₃) sulfonate"),
    ),
    _m(
        "sulfone",
        "Sulfone –SO₂–",
        FAMILY_SULFUR_PHOSPHORUS,
        "[#6][SX4:1](=[OX1:2])(=[OX1:3])[#6]",
        ("νas(SO₂) sulfone", "νs(SO₂) sulfone"),
    ),
    _m(
        "sulfoxide",
        "Sulfoxide S=O",
        FAMILY_SULFUR_PHOSPHORUS,
        ("[#6][SX3:1](=[OX1:2])[#6]", "[#6][SX3+:1]([OX1-:2])[#6]"),
        ("ν(S=O) sulfoxide",),
    ),
    _m(
        "thiol",
        "Thiol –SH",
        FAMILY_SULFUR_PHOSPHORUS,
        "[#6][SX2H1:1]",
        ("ν(SH) thiol", "ν(C–S) sulfide/thioether"),
    ),
    _m(
        "sulfide",
        "Sulfide / disulfide",
        FAMILY_SULFUR_PHOSPHORUS,
        "[#6][SX2;!a:1][#6,#16]",
        ("ν(C–S) sulfide/thioether",),
    ),
    _m(
        "phosphate_aryl",
        "Aryl phosphate / phosphonate P–O–Ar",
        FAMILY_SULFUR_PHOSPHORUS,
        "[PX4:1](=[OX1:2])[OX2:3]c",
        ("ν(P=O) phosphoryl", "ν(P–O–Ar)"),
    ),
    _m(
        "phosphate",
        "Phosphate / phosphonate ester",
        FAMILY_SULFUR_PHOSPHORUS,
        "[PX4:1](=[OX1:2])[OX2:3][#6]",
        ("ν(P=O) phosphoryl", "ν(P–O–C) aliph. phosphate"),
    ),
    _m(
        "phosphoric_acid",
        "Phosphoric / phosphonic acid P–OH",
        FAMILY_SULFUR_PHOSPHORUS,
        "[PX4:1](=[OX1:2])[OX2H1:3]",
        ("ν(P=O) phosphoryl", "ν(OH) P–OH"),
    ),
    _m(
        "phosphine_oxide",
        "Phosphine oxide R₃P=O",
        FAMILY_SULFUR_PHOSPHORUS,
        "[PX4:1](=[OX1:2])([#6])([#6])[#6]",
        ("ν(P=O) phosphine oxide",),
    ),
    _m(
        "thiophosphate",
        "Thiophosphoryl P=S",
        FAMILY_SULFUR_PHOSPHORUS,
        "[PX4:1]=[SX1:2]",
        ("ν(P=S)",),
    ),
    _m(
        "boronate_pinacol",
        "Pinacol boronate (Bpin)",
        FAMILY_SULFUR_PHOSPHORUS,
        "[B:1]1[O:2]C(C)(C)C(C)(C)[O:3]1",
        ("νas(B–O) boronic acid/ester", "ν(C–O) pinacol boronate", "δs(CH₃) (CH₃)₂CH isopropyl"),
    ),
    _m(
        "boronic_acid",
        "Boronic acid / ester –B(OR)₂",
        FAMILY_SULFUR_PHOSPHORUS,
        "[#6][BX3:1]([OX2:2])[OX2:3]",
        ("νas(B–O) boronic acid/ester", "ν(OH) B(OH)₂"),
    ),
    _m(
        "tbdps",
        "TBDPS silyl ether",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:1](c)(c)([CX4]([CH3])([CH3])[CH3])[OX2:2]",
        ("ν(Si–Ph) TBDPS", "ν(Si–O–C) silyl ether", "δ(CH₃) t-Bu dublet (silyl)"),
    ),
    _m(
        "tips",
        "TIPS silyl ether",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:1]([CH1]([CH3])[CH3])([CH1]([CH3])[CH3])[CH1]([CH3])[CH3]",
        (
            "ρ(CH₃) iPr TIPS",
            "ν(CCC) TIPS",
            "νas(CCC) TIPS",
            "δ(CH₃) iPr TIPS",
            "ν(Si–O–C) silyl ether",
        ),
    ),
    _m(
        "tbs",
        "TBS / TBDMS silyl ether",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:1]([CH3])([CH3])[CX4]([CH3])([CH3])[CH3]",
        (
            "δs(Si–CH₃) TMS/TBS",
            "ρ(Si–CH₃) TBS",
            "ω(t-Bu) TBS",
            "νas(Si–C) TBS",
            "δ(CH₃) t-Bu dublet (silyl)",
            "ν(Si–O–C) silyl ether",
        ),
    ),
    _m(
        "tms",
        "TMS (trimethylsilyl)",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:1]([CH3])([CH3])[CH3]",
        (
            "δs(Si–CH₃) TMS/TBS",
            "δa(Si–CH₃)",
            "ρ(CH₃) Si(CH₃)₃ TMS",
            "νas(Si–C₃) TMS",
            "νs(Si–C₃) TMS",
        ),
    ),
    _m(
        "siloxane",
        "Siloxane Si–O–Si (silicone)",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:2][OX2:1][Si:3]",
        ("νas(Si–O–Si) siloxane", "δs(Si–CH₃) silicone", "ν(Si–C)+ρ(CH₃) silicone"),
    ),
    _m(
        "silyl_ether",
        "Silyl ether Si–O–C",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si:2][OX2:1][#6]",
        ("ν(Si–O–C) silyl ether",),
    ),
    _m(
        "silane_h",
        "Si–H",
        FAMILY_SULFUR_PHOSPHORUS,
        "[Si;!H0:1]",
        ("ν(Si–H)",),
    ),
    # ── Heteroaromatic rings ─────────────────────────────────────────────────
    _m(
        "tetrazole",
        "Tetrazole",
        FAMILY_HETEROCYCLE,
        "[#6:1]1:[#7:2]:[#7:3]:[#7:4]:[#7:5]:1",
        (
            "ν(NH) azole (H-bonded)",
            "ν(C=N) tetrazole ring",
            "ν(N=N) tetrazole ring",
            "ring δ tetrazole",
        ),
    ),
    _m(
        "triazole_123",
        "1,2,3-Triazole",
        FAMILY_HETEROCYCLE,
        "[#6:1]1:[#6:2]:[#7:3]:[#7:4]:[#7:5]:1",
        (
            "ν(CH) azole ring C–H",
            "ν(N=N) 1,2,3-triazole ring",
            "ν(ring) 1,2,3-triazole",
            "ring breathing triazole",
            "ν(NH) azole (H-bonded)",
        ),
    ),
    _m(
        "triazole_124",
        "1,2,4-Triazole",
        FAMILY_HETEROCYCLE,
        "[#6:1]1:[#7:2]:[#6:3]:[#7:4]:[#7:5]:1",
        (
            "ν(CH) azole ring C–H",
            "ν(C=N) 1,2,4-triazole ring",
            "ring breathing triazole",
            "ν(NH) azole (H-bonded)",
        ),
    ),
    _m(
        "oxadiazole",
        "Oxadiazole",
        FAMILY_HETEROCYCLE,
        ("[#8:1]1:[#6:2]:[#7:3]:[#7:4]:[#6:5]:1", "[#8:1]1:[#7:2]:[#6:3]:[#7:4]:[#6:5]:1"),
        ("ν(C=N) oxazole/isoxazole/oxadiazole", "ν(C–O–C) oxazole/oxadiazole ring"),
    ),
    _m(
        "isoxazole",
        "Isoxazole / benzisoxazole",
        FAMILY_HETEROCYCLE,
        "[#8:1]1:[#7:2]:[#6:3]:[#6:4]:[#6:5]:1",
        (
            "ν(C=N) oxazole/isoxazole/oxadiazole",
            "ν(C–O–C) oxazole/oxadiazole ring",
        ),
    ),
    _m(
        "oxazole",
        "Oxazole / benzoxazole",
        FAMILY_HETEROCYCLE,
        "[#8:1]1:[#6:2]:[#7:3]:[#6:4]:[#6:5]:1",
        (
            "ν(C=N) oxazole/isoxazole/oxadiazole",
            "ν(C–O–C) oxazole/oxadiazole ring",
            "ν(CH) azole ring C–H",
        ),
    ),
    _m(
        "thiazole",
        "Thiazole",
        FAMILY_HETEROCYCLE,
        ("[#16:1]1:[#6:2]:[#7:3]:[#6:4]:[#6:5]:1", "[#16:1]1:[#7:2]:[#6:3]:[#6:4]:[#6:5]:1"),
        ("ν(ring) thiazole", "ν(CH) azole ring C–H"),
    ),
    _m(
        "imidazole",
        "Imidazole / benzimidazole",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#6:2]:[#7:3]:[#6:4]:[#6:5]:1",
        ("ν(NH) azole (H-bonded)", "ν(C=N) imidazole ring", "ν(CH) azole ring C–H"),
    ),
    _m(
        "pyrazole",
        "Pyrazole / indazole",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#7:2]:[#6:3]:[#6:4]:[#6:5]:1",
        ("ν(NH) azole (H-bonded)", "ν(C=N) pyrazole ring", "ν(CH) azole ring C–H"),
    ),
    _m(
        "pyrrole",
        "Pyrrole / indole",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#6:2]:[#6:3]:[#6:4]:[#6:5]:1",
        ("ν(NH) pyrrole/indole", "ν(ring) pyrrole/indole", "ν(CH) Ar"),
    ),
    _m(
        "furan",
        "Furan / benzofuran",
        FAMILY_HETEROCYCLE,
        "[#8:1]1:[#6:2]:[#6:3]:[#6:4]:[#6:5]:1",
        ("ν(CH) furan/thiophene", "ν(ring) furan", "ring breathing furan", "γ(CH) furan"),
    ),
    _m(
        "thiophene",
        "Thiophene / benzothiophene",
        FAMILY_HETEROCYCLE,
        "[#16:1]1:[#6:2]:[#6:3]:[#6:4]:[#6:5]:1",
        ("ν(CH) furan/thiophene", "ν(ring) thiophene", "γ(CH) thiophene"),
    ),
    _m(
        "pyrazine",
        "Pyrazine / quinoxaline",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#6:2]:[#6:3]:[#7:4]:[#6:5]:[#6:6]:1",
        ("ν(ring) diazine", "ν(ring) diazine ~1410", "ν(CH) Ar"),
    ),
    _m(
        "diazine",
        "Pyrimidine / pyridazine / triazine",
        FAMILY_HETEROCYCLE,
        (
            "[#7:1]1:[#6:2]:[#7:3]:[#6:4]:[#6:5]:[#6:6]:1",
            "[#7:1]1:[#7:2]:[#6:3]:[#6:4]:[#6:5]:[#6:6]:1",
            "[#7:1]1:[#6:2]:[#7:3]:[#6:4]:[#7:5]:[#6:6]:1",
        ),
        ("ν(ring) diazine", "ν(ring) diazine ~1410", "ν(CH) Ar"),
    ),
    _m(
        "quinoline",
        "Quinoline",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#6:2]:[#6:3]:[#6:4]:[#6:5]2:[#6]:[#6]:[#6]:[#6]:[#6:6]:1:2",
        ("ν(CH) Ar", "ν(ring) pyridine ~1590"),
    ),
    _m(
        "pyridine",
        "Pyridine / isoquinoline",
        FAMILY_HETEROCYCLE,
        "[#7:1]1:[#6:2]:[#6:3]:[#6:4]:[#6:5]:[#6:6]:1",
        (
            "ν(CH) Ar",
            "ν(ring) pyridine ~1590",
            "ν(ring) pyridine ~1440",
            "ring breathing pyridine",
            "γ(CH) Ar 3H adjacent",
        ),
    ),
    # ── Oxygen groups ────────────────────────────────────────────────────────
    _m(
        "epoxide",
        "Epoxide (oxirane)",
        FAMILY_OXYGEN,
        "[CX4:1]1[OX2:2][CX4:3]1",
        ("ν(ring) oxirane breathing", "νas(ring) oxirane"),
    ),
    _m(
        "acetal",
        "Acetal / ketal",
        FAMILY_OXYGEN,
        "[OX2;!$(O[#6]=O);!$(O[Si,P,S,B]):1][CX4:2][OX2;!$(O[#6]=O);!$(O[Si,P,S,B]):3]",
        ("ν(C–O–C) acetal/ketal", "ν(CO) R–O–R aliph. ether"),
    ),
    _m(
        "phenol",
        "Phenol Ar–OH",
        FAMILY_OXYGEN,
        "c[OX2H1:1]",
        _OH_STRETCH + ("δ(COH) tert./Ar–OH", "ν(CO) Ar–OH phenol"),
    ),
    _m(
        "tertiary_alcohol",
        "Tertiary alcohol",
        FAMILY_OXYGEN,
        "[OX2H1:1][CX4H0:2]([#6])([#6])[#6]",
        _OH_STRETCH + ("δ(COH) tert./Ar–OH", "ν(CO) R₃C–OH tert."),
    ),
    _m(
        "secondary_alcohol",
        "Secondary alcohol",
        FAMILY_OXYGEN,
        "[OX2H1:1][CX4H1:2]([#6])[#6]",
        _OH_STRETCH + ("δ(COH) R–OH prim./sec.", "ν(CO) R₂CH–OH sec."),
    ),
    _m(
        "primary_alcohol",
        "Primary alcohol (incl. methanol)",
        FAMILY_OXYGEN,
        ("[OX2H1:1][CX4H2:2][#6]", "[OX2H1:1][CH3:2]"),
        _OH_STRETCH + ("δ(COH) R–OH prim./sec.", "ν(CO) R–OH prim."),
    ),
    _m(
        "vinyl_ether",
        "Vinyl / enol ether",
        FAMILY_OXYGEN,
        "[OX2;!$(O[#6]=O):1]([#6])[CX3;!a]=[CX3;!a]",
        ("ν(CO) CH₂=CH–O– vinyl ether", "ν(C=C) >C=C< alkene"),
    ),
    _m(
        "aryl_ether",
        "Aryl ether Ar–O–R",
        FAMILY_OXYGEN,
        "c[OX2;!$(O[#6]=O);!$(O-[Si,P,S,B,N]):1][#6]",
        ("ν(CO) Ar–O–R aryl ether", "νs(COC) Ar–O–CH₃"),
    ),
    _m(
        "cyclic_ether",
        "Cyclic ether (THF, THP, dioxane, morpholine)",
        FAMILY_OXYGEN,
        "[CX4;R][OX2;R;!$(O[#6]=O):1][CX4;R]",
        ("ν(COC) cyclic ether THF/THP", "ν(CO) R–O–R aliph. ether"),
    ),
    _m(
        "dialkyl_ether",
        "Aliphatic ether R–O–R",
        FAMILY_OXYGEN,
        "[CX4][OX2;!$(O[#6]=O);!$(O-[Si,P,S,B,N]):1][CX4]",
        ("ν(CO) R–O–R aliph. ether", "ρ(CH₂) propyl/(CH₂)n–O–"),
    ),
    # ── Double and triple bonds ──────────────────────────────────────────────
    _m(
        "allene",
        "Allene C=C=C",
        FAMILY_UNSATURATED,
        "[CX3:1]=[CX2:2]=[CX3:3]",
        ("ν(C=C=C) allene",),
    ),
    _m(
        "ketene",
        "Ketene C=C=O",
        FAMILY_UNSATURATED,
        "[CX3:1]=[CX2:2]=[OX1:3]",
        ("ν(C=C=O) ketene",),
    ),
    _m(
        "terminal_alkyne",
        "Terminal alkyne –C≡C–H",
        FAMILY_UNSATURATED,
        "[CX2H1:1]#[CX2:2]",
        ("ν(CH) –C≡C–H", "ν(C≡C) –C≡C–H", "δ(CH) –C≡C–H", "δ(CH) –C≡C–H in-plane"),
    ),
    _m(
        "internal_alkyne",
        "Internal alkyne –C≡C–",
        FAMILY_UNSATURATED,
        "[#6][CX2:1]#[CX2:2][#6]",
        ("ν(C≡C) –C≡C– disubst.",),
    ),
    _m(
        "conjugated_diene",
        "Conjugated diene / polyene",
        FAMILY_UNSATURATED,
        "[CX3;!a:1]=[CX3;!a:2][CX3;!a:3]=[CX3;!a:4]",
        ("ν(C=C) –C=C–C=C– conj.", "ν(CH) =CH–"),
    ),
    _m(
        "vinyl",
        "Vinyl –CH=CH₂",
        FAMILY_UNSATURATED,
        "[CX3H2;!a:1]=[CX3H1;!a:2]",
        (
            "ν(C=C) >C=C< alkene",
            "ν(CH) =CH–",
            "δ(CH₂) –HC=CH₂",
            "γ(CH) –CH=CH₂ vinyl",
            "γ(CH) R–CH=CH₂ terminal",
            "2×γ(CH) vinyl/vinylidene",
        ),
    ),
    _m(
        "vinylidene",
        "Vinylidene >C=CH₂",
        FAMILY_UNSATURATED,
        "[CX3H2;!a:1]=[CX3H0;!a:2]",
        (
            "ν(C=C) >C=C< alkene",
            "νas(CH₂) >C=CH₂",
            "γ(CH) RR'C=CH₂ vinylidene",
            "2×γ(CH) vinyl/vinylidene",
        ),
    ),
    _m(
        "trans_alkene",
        "trans-Alkene –CH=CH–",
        FAMILY_UNSATURATED,
        _DISUBSTITUTED_ALKENE,
        ("ν(C=C) >C=C< alkene", "ν(CH) =CH–", "δ(CH) –HC=CH– trans", "γ(CH) R–CH=CH–R trans"),
        geometry="trans",
    ),
    _m(
        "cis_alkene",
        "cis-Alkene –CH=CH–",
        FAMILY_UNSATURATED,
        _DISUBSTITUTED_ALKENE,
        ("ν(C=C) >C=C< alkene", "ν(CH) =CH–", "δ(CH) –CH=CH– cis", "γ(CH) R–CH=CH–R' cis"),
        geometry="cis",
    ),
    _m(
        "disubstituted_alkene",
        "1,2-Disubstituted alkene (geometry not drawn)",
        FAMILY_UNSATURATED,
        _DISUBSTITUTED_ALKENE,
        (
            "ν(C=C) >C=C< alkene",
            "ν(CH) =CH–",
            "γ(CH) R–CH=CH–R trans",
            "γ(CH) R–CH=CH–R' cis",
        ),
        geometry="unknown",
    ),
    _m(
        "trisubstituted_alkene",
        "Trisubstituted alkene",
        FAMILY_UNSATURATED,
        "[#6][CX3H1;!a:1]=[CX3H0;!a:2]([#6])[#6]",
        ("ν(C=C) >C=C< alkene", "δ(CH) >C=CH–", "γ(CH) RR'C=CHR'' trisubst."),
    ),
    _m(
        "tetrasubstituted_alkene",
        "Tetrasubstituted alkene",
        FAMILY_UNSATURATED,
        "[#6][CX3H0;!a:1]([#6])=[CX3H0;!a:2]([#6])[#6]",
        ("ν(C=C) >C=C< alkene",),
    ),
    # ── Halogens ─────────────────────────────────────────────────────────────
    _m(
        "trifluoromethyl",
        "Trifluoromethyl –CF₃",
        FAMILY_HALOGEN,
        "[CX4:1](F)(F)F",
        ("νas(CF₃)", "ν(C–F)"),
    ),
    _m("fluoro", "C–F", FAMILY_HALOGEN, "[#6]-[F:1]", ("ν(C–F)",)),
    _m("aryl_chloride", "Aryl chloride Ar–Cl", FAMILY_HALOGEN, "c[Cl:1]", ("ν(C–Cl) Ar–Cl",)),
    _m("alkyl_chloride", "Alkyl chloride C–Cl", FAMILY_HALOGEN, "[CX4][Cl:1]", ("ν(C–Cl) alkyl",)),
    _m("bromide", "C–Br", FAMILY_HALOGEN, "[#6][Br:1]", ("ν(C–Br)",)),
    _m("iodide", "C–I", FAMILY_HALOGEN, "[#6][I:1]", ("ν(C–I)",)),
    # ── Additive skeleton motifs (never claim atoms) ─────────────────────────
    _m(
        "aromatic_ring",
        "Aromatic ring (C–H, ring stretches)",
        FAMILY_AROMATIC,
        "[c;H1]",
        _AR_RING,
        exclusive=False,
    ),
    _m(
        "polycyclic_aromatic",
        "Fused aromatic (naphthalene, …)",
        FAMILY_AROMATIC,
        "c12ccccc1cccc2",
        ("γ(CH) Ar 4H 1,2-disubst.", "γ(CH) Ar 2H adjacent", "γ(CH) Ar 3H adjacent"),
        exclusive=False,
    ),
    _m(
        "indane",
        "Indane (benzo-fused cyclopentane)",
        FAMILY_AROMATIC,
        "[CX4:1]1[CX4][CX4]c2ccccc12",
        ("δ(CH₂) –CH₂–",),
        exclusive=False,
    ),
    _m(
        "biphenyl",
        "Biphenyl",
        FAMILY_AROMATIC,
        "[c:1]1ccccc1-!@c1ccccc1",
        ("ν(CH) Ar",),
        exclusive=False,
    ),
    _m(
        "acetate",
        "Acetate –O–CO–CH₃ (OAc)",
        FAMILY_ALKYL,
        "[CH3][#6X3:1](=[OX1])[OX2][#6]",
        ("δs(CH₃) CH₃–C=O", "δd(CH₃) CH₃–C=O/N/S"),
        exclusive=False,
    ),
    _m(
        "tert_butoxy",
        "tert-Butoxy –OC(CH₃)₃ (Boc, t-Bu ester / ether)",
        FAMILY_ALKYL,
        "[CH3][CX4:1]([CH3])([CH3])[OX2]",
        ("–C(CH₃)₃ tert-butyl",),
        exclusive=False,
    ),
    _m(
        "tert_butyl",
        "tert-Butyl –C(CH₃)₃",
        FAMILY_ALKYL,
        "[CH3][CX4:1]([CH3])([CH3])[!#1]",
        ("–C(CH₃)₃ tert-butyl", "δs(CH₃) (CH₃)₂CH isopropyl", "νas(CH₃) –CH₃"),
        exclusive=False,
    ),
    _m(
        "gem_dimethyl",
        "Isopropyl / gem-dimethyl",
        FAMILY_ALKYL,
        ("[CH3][CX4H1:1][CH3]", "[CH3][CX4H0:1]([CH3])([!$([CH3])])[!$([CH3])]"),
        ("δs(CH₃) (CH₃)₂CH isopropyl", "ν(CC) –CH(CH₃)₂"),
        exclusive=False,
    ),
    _m(
        "methoxy",
        "Methoxy –OCH₃",
        FAMILY_ALKYL,
        "[CH3:1][OX2;!$(O[#6]=O)][#6]",
        ("νs(CH₃) O–CH₃ methoxy",),
        exclusive=False,
    ),
    _m(
        "n_methyl",
        "N-Methyl –NCH₃",
        FAMILY_ALKYL,
        "[CH3:1][#7X3]",
        ("νs(CH₃) N–CH₃", "δd(CH₃) CH₃–C=O/N/S"),
        exclusive=False,
    ),
    _m(
        "acetyl",
        "Acetyl / methyl on C=O, S",
        FAMILY_ALKYL,
        ("[CH3:1][CX3]=O", "[CH3:1][SX2,SX3,SX4]"),
        ("δs(CH₃) CH₃–C=O", "δd(CH₃) CH₃–C=O/N/S"),
        exclusive=False,
    ),
    _m(
        "cyclopropyl",
        "Cyclopropyl",
        FAMILY_ALKYL,
        "[CX4:1]1[CX4][CX4]1",
        ("ν(CH) cyclopropane", "ring δ cyclopropane"),
        exclusive=False,
    ),
    _m(
        "long_chain",
        "Long chain –(CH₂)n– (n ≥ 4)",
        FAMILY_ALKYL,
        "[CH2X4;!R:1][CH2X4;!R][CH2X4;!R][CH2X4;!R]",
        ("ρ(CH₂) (CH₂)n– n>3",),
        exclusive=False,
    ),
    _m(
        "methylene",
        "Methylene –CH₂–",
        FAMILY_ALKYL,
        "[CH2X4:1]",
        ("νas(CH₂) –CH₂–", "νs(CH₂) –CH₂–", "δ(CH₂) –CH₂–", "ρ(CH₂) adj. CHx≠2"),
        exclusive=False,
    ),
    _m(
        "methyl",
        "Methyl –CH₃",
        FAMILY_ALKYL,
        "[CH3X4:1]",
        ("νas(CH₃) –CH₃", "νs(CH₃) –CH₃", "δd(CH₃) –CH₃"),
        exclusive=False,
    ),
    _m(
        "methine",
        "Methine >CH–",
        FAMILY_ALKYL,
        "[CH1X4:1]",
        ("ν(CH) sat.",),
        exclusive=False,
    ),
)

# Bands verified on the laboratory's own evaluated spectra (100 projects with
# structures; see the seed-version-3 block of the built-in vibration library),
# appended to the motifs they belong to.
_LAB_VIBRATIONS: dict[str, tuple[str, ...]] = {
    "methyl": ("δs(CH₃) –CH₃ umbrella",),
    "methylene": ("ω(CH₂) –CH₂– wagging",),
    "tert_butyl": ("δs(CH₃) t-Bu doublet",),
    "tert_butoxy": ("ν(O–C(CH₃)₃) t-Bu ester/Boc", "δs(CH₃) t-Bu doublet"),
    "acetate": ("νas(C–O) acetate ~1230", "νs(O–C–C) acetate ~1045", "δ(O–C=O) acetate ~605"),
    "tertiary_amide": ("ν(C–N) tert. amide ~1410",),
    "gamma_lactam": (
        "ν(NH) lactam cis-NH (2-pyrrolidone)",
        "δ(NH) lactam cis-NH (2-pyrrolidone)",
        "2-pyrrolidone ring ~1457",
        "2-pyrrolidone ring ~1290",
        "2-pyrrolidone ring ~1154",
        "2-pyrrolidone ring ~888",
        "2-pyrrolidone ring ~621",
    ),
    "pyridone": (
        "2-pyridone ring ~1359",
        "2-pyridone ring ~1326",
        "2-pyridone ring ~1236",
        "2-pyridone ring ~1136",
        "2-pyridone ring ~1052",
        "2-pyridone ring ~876",
        "2-pyridone ring ~768",
        "2-pyridone ring ~752",
        "2-pyridone ring ~559",
        "2-pyridone ring ~458",
    ),
    "quinoline": (
        "ν(CH) quinoline",
        "quinoline ring ~1426",
        "quinoline ring ~1392",
        "quinoline ring ~1330",
        "quinoline ring ~1305",
        "quinoline ring ~1098",
        "quinoline ring ~789",
        "quinoline ring ~749",
    ),
    "pyridine": (
        "pyridine ring ~1597",
        "pyridine ring ~1372",
        "pyridine ring ~1146",
        "pyridine ring ~1078",
        "pyridine ring ~1049",
        "pyridine ring ~972",
        "pyridine ring ~826",
        "pyridine ring ~786",
        "pyridine ring ~711",
        "pyridine ring ~664",
    ),
    "pyrazine": (
        "pyrazine ring ~1576",
        "pyrazine ring ~1549",
        "pyrazine ring ~1416",
        "pyrazine ring ~1368",
        "pyrazine ring ~1216",
        "pyrazine ring ~1082",
        "pyrazine ring ~1003",
        "pyrazine ring ~923",
        "pyrazine ring ~773",
        "pyrazine ring ~723",
        "pyrazine ring ~594",
    ),
    "isoxazole": (
        "ν(CH) isoxazole",
        "isoxazole ring ~1559",
        "isoxazole ring ~1270",
        "isoxazole ring ~1085",
        "isoxazole ring ~924",
    ),
    "indane": (
        "indane ring ~1273",
        "indane ring ~1022",
        "indane ring ~925",
        "indane ring ~831",
        "indane ring ~754",
    ),
    "biphenyl": (
        "biphenyl ring ~1437",
        "biphenyl ring ~1159",
        "biphenyl ring ~1076",
        "biphenyl ring ~1008",
        "biphenyl ring ~756",
        "biphenyl ring ~697",
    ),
    "polycyclic_aromatic": (
        "ν(CH) naphthalene",
        "naphthalene ring ~1390",
        "naphthalene ring ~1365",
        "naphthalene ring ~1285",
        "naphthalene ring ~1145",
        "naphthalene ring ~954",
        "naphthalene ring ~774",
    ),
    "trifluoromethyl": ("νs(CF₃) Ar–CF₃",),
    "tips": (
        "νas(Si–C₃) TIPS",
        "νs(Si–C₃) TIPS",
        "ρ(CH₃) TIPS ~995",
        "δs(CH₃) iPr TIPS doublet",
    ),
    "sulfate": ("νas(SO₃⁻) sulfate/sulfonate anion", "δs(SO₃⁻)", "ν(S–O–C) sulfate ester"),
    "sulfonate": ("νas(SO₃⁻) sulfate/sulfonate anion", "δs(SO₃⁻)"),
    "sulfonamide": ("δ(SO₂) scissoring",),
    "sulfone": ("δ(SO₂) scissoring",),
    "sulfonyl_chloride": ("δ(SO₂) scissoring",),
    "ammonium": (
        "νas(NH₃⁺) R–NH₃⁺",
        "ν(NH⁺) ammonium salt broad",
        "comb. R–NH₃⁺ salt indicator ~2030",
        "δas(NH₃⁺) R–NH₃⁺",
        "δs(NH₃⁺) R–NH₃⁺",
        "ρ(NH₃⁺) R–NH₃⁺",
    ),
}
MOTIFS = tuple(
    replace(motif, vibrations=motif.vibrations + _LAB_VIBRATIONS.get(motif.id, ()))
    for motif in MOTIFS
)

_BENZENE_SUBSTITUTION_VIBRATIONS: dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]] = {
    (): ("benzene", "Benzene (unsubstituted)", ("γ(CH) Ar 6H benzene ~670",)),
    (1,): (
        "monosubstituted_benzene",
        "Monosubstituted benzene",
        ("γ(CH) Ar 5H monosubst.", "γ(CH) Ar mono/1,3-/1,2,3-/1,2,4-"),
    ),
    (1, 2): ("ortho_benzene", "1,2-Disubstituted benzene (ortho)", ("γ(CH) Ar 4H 1,2-disubst.",)),
    (1, 3): (
        "meta_benzene",
        "1,3-Disubstituted benzene (meta)",
        ("γ(CH) Ar 3H adjacent", "γ(CH) Ar 1H isolated", "γ(CH) Ar mono/1,3-/1,2,3-/1,2,4-"),
    ),
    (1, 4): (
        "para_benzene",
        "1,4-Disubstituted benzene (para)",
        (
            "γ(CH) Ar 2H adjacent",
            "para-disubst. benzene ring ~1224",
            "para-disubst. benzene ring ~1182",
            "para-disubst. benzene ring ~1107",
            "para-disubst. benzene ring ~816",
        ),
    ),
    (1, 2, 3): (
        "benzene_123",
        "1,2,3-Trisubstituted benzene",
        ("γ(CH) Ar 3H adjacent", "γ(CH) Ar mono/1,3-/1,2,3-/1,2,4-"),
    ),
    (1, 2, 4): (
        "benzene_124",
        "1,2,4-Trisubstituted benzene",
        ("γ(CH) Ar 2H adjacent", "γ(CH) Ar 1H isolated", "γ(CH) Ar mono/1,3-/1,2,3-/1,2,4-"),
    ),
    (1, 3, 5): ("benzene_135", "1,3,5-Trisubstituted benzene", ("γ(CH) Ar 1H isolated",)),
    (1, 2, 3, 4): (
        "benzene_1234",
        "Tetrasubstituted benzene (2 adjacent H)",
        ("γ(CH) Ar 2H adjacent",),
    ),
    (1, 2, 4, 5): (
        "benzene_1245",
        "Tetrasubstituted benzene (isolated H)",
        ("γ(CH) Ar 1H isolated",),
    ),
    (1, 2, 3, 5): (
        "benzene_1235",
        "Tetrasubstituted benzene (isolated H)",
        ("γ(CH) Ar 1H isolated",),
    ),
    (1, 2, 3, 4, 5): ("benzene_penta", "Pentasubstituted benzene", ("γ(CH) Ar 1H isolated",)),
}
_BENZENE_MOTIFS = {
    key: Motif(mid, name, FAMILY_AROMATIC, (), vib, exclusive=False)
    for key, (mid, name, vib) in _BENZENE_SUBSTITUTION_VIBRATIONS.items()
}

#: Every motif the perception can report (for tests and documentation).
ALL_MOTIFS: tuple[Motif, ...] = MOTIFS + tuple(_BENZENE_MOTIFS.values())


@cache
def _compiled(smarts: str) -> tuple[Any, tuple[int, ...], int]:
    """Pattern, the indices of its core (mapped) atoms, and its key atom.

    The key atom is the one mapped ``:1`` — the atom that *is* the group (the
    carbonyl carbon of an ester, the oxygen of an ether). A match is blocked
    when its key atom already belongs to a more specific motif; sharing another
    core atom is allowed, so the two carbonyls of a xanthine that share a
    nitrogen are both reported.
    """
    pattern = Chem.MolFromSmarts(smarts)
    if pattern is None:  # pragma: no cover - guarded by the test suite
        raise ValueError(f"invalid SMARTS: {smarts}")
    mapped = {
        atom.GetAtomMapNum(): atom.GetIdx()
        for atom in pattern.GetAtoms()
        if atom.GetAtomMapNum() > 0
    }
    core = tuple(sorted(mapped.values())) or tuple(range(pattern.GetNumAtoms()))
    key = mapped.get(1, core[0])
    return pattern, core, key


def perceive_motifs(mol: Any) -> list[FoundMotif]:
    """Every catalog motif found in an RDKit molecule, specific before general."""
    if mol is None or mol.GetNumAtoms() == 0:
        return []
    claimed: set[int] = set()
    found: list[FoundMotif] = []
    for motif in MOTIFS:
        accepted: list[tuple[int, ...]] = []
        seen_cores: set[frozenset[int]] = set()
        for smarts in motif.smarts:
            pattern, core_indices, key_index = _compiled(smarts)
            for match in mol.GetSubstructMatches(pattern, useChirality=False):
                core = frozenset(match[i] for i in core_indices)
                if core in seen_cores:
                    continue
                if motif.exclusive and match[key_index] in claimed:
                    continue
                if motif.geometry and _alkene_geometry(mol, match) != motif.geometry:
                    continue
                seen_cores.add(core)
                accepted.append(tuple(sorted(core)))
                if motif.exclusive:
                    claimed |= core
        if accepted:
            found.append(FoundMotif(motif=motif, matches=tuple(accepted)))
    found.extend(_benzene_rings(mol))
    salt = _amine_salt(mol, found)
    if salt is not None:
        found = [f for f in found if f.id != "ammonium"] + [salt]
    order = {family: index for index, family in enumerate(FAMILIES)}
    position = {motif.id: index for index, motif in enumerate(ALL_MOTIFS)}
    found.sort(key=lambda f: (order.get(f.motif.family, 99), position.get(f.motif.id, 999)))
    return found


# Abbreviations older projects carry inside their SMILES ("[OAc]", "[HCl]"),
# expanded so those structures can still be read.
_SMILES_ABBREVIATIONS = (
    ("[OAc]", "OC(C)=O"),
    ("[OBn]", "OCc9ccccc9"),
    ("[OMe]", "OC"),
    ("[OTr]", "OC(c9ccccc9)(c9ccccc9)c9ccccc9"),
    ("[Boc]", "C(=O)OC(C)(C)C"),
    ("[HCl]", "Cl"),
    ("[HBr]", "Br"),
)


def parse_structure(smiles: str) -> Any:
    """RDKit molecule for a drawing's SMILES, abbreviations expanded; ``None`` if unreadable."""
    if not smiles:
        return None
    from rdkit import RDLogger  # noqa: PLC0415

    RDLogger.DisableLog("rdApp.*")
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            expanded = smiles
            for short, full in _SMILES_ABBREVIATIONS:
                expanded = expanded.replace(short, full)
            # Stray tokens such as "[.6]" (a stoichiometry note) are dropped.
            expanded = re.sub(r"\.?\[\.[^\]]*\]", "", expanded)
            mol = Chem.MolFromSmiles(expanded) if expanded != smiles else None
    finally:
        RDLogger.EnableLog("rdApp.*")
    return mol


def perceive_smiles(smiles: str) -> list[FoundMotif]:
    """``perceive_motifs`` for a SMILES string (empty list when it does not parse).

    A drawing may hold several molecules (a salt, a mixture); all of them count.
    """
    mol = parse_structure(smiles)
    if mol is None:
        return []
    return perceive_motifs(mol)


_BASIC_AMINE = "[NX3;!$(N[#6,#16,#15]=[O,S,N]);!$(N-a);!$(N-[N,O,S]);!a]"
_ACID_FRAGMENT = "[$([Cl,Br,I;D0]),$([Cl-,Br-,I-]),$([OX2H1][SX4](=O)=O),$([OX2H1][PX4]=O)]"


def _amine_salt(mol: Any, found: list[FoundMotif]) -> FoundMotif | None:
    """An amine drawn next to its acid (``R-NH2 . HCl``) is an ammonium salt.

    Salts are often drawn neutral with the acid as a separate part — a
    hydrochloride as ``.Cl``, a triethylammonium salt as ``Et3N`` next to a
    sulfonic acid — so ``[NH3+]`` never appears. When a drawing holds such an
    acid and a basic amine, the ammonium bands are offered as well.
    """
    existing = next((f for f in found if f.id == "ammonium"), None)
    fragments = Chem.GetMolFrags(mol, asMols=True)
    if len(fragments) < 2:
        return existing
    acid = _pattern_once(_ACID_FRAGMENT)
    amine = _pattern_once(_BASIC_AMINE)
    if not any(fragment.HasSubstructMatch(acid) for fragment in fragments):
        return existing
    amines = tuple((match[0],) for match in mol.GetSubstructMatches(amine))
    if not amines:
        return existing
    motif = next(m for m in MOTIFS if m.id == "ammonium")
    matches = tuple(dict.fromkeys((existing.matches if existing else ()) + amines))
    return FoundMotif(motif=motif, matches=matches)


@cache
def _pattern_once(smarts: str) -> Any:
    return Chem.MolFromSmarts(smarts)


def _benzene_rings(mol: Any) -> list[FoundMotif]:
    """Substitution pattern of every isolated benzene ring."""
    found: dict[str, list[tuple[int, ...]]] = {}
    ring_info = mol.GetRingInfo()
    for ring in ring_info.AtomRings():
        if len(ring) != 6:
            continue
        atoms = [mol.GetAtomWithIdx(i) for i in ring]
        if not all(a.GetSymbol() == "C" and a.GetIsAromatic() for a in atoms):
            continue
        if any(ring_info.NumAtomRings(i) > 1 for i in ring):
            continue
        ring_set = set(ring)
        substituted = [
            position
            for position, atom in enumerate(atoms)
            if any(n.GetIdx() not in ring_set and n.GetAtomicNum() > 1 for n in atom.GetNeighbors())
        ]
        key = _lowest_locants(substituted)
        motif = _BENZENE_MOTIFS.get(key)
        if motif is not None:
            found.setdefault(motif.id, []).append(tuple(sorted(ring)))
    by_id = {m.id: m for m in _BENZENE_MOTIFS.values()}
    return [FoundMotif(motif=by_id[mid], matches=tuple(rings)) for mid, rings in found.items()]


def _alkene_geometry(mol: Any, match: tuple[int, ...]) -> str:
    """cis / trans of a drawn 1,2-disubstituted double bond, else "unknown"."""
    bond = mol.GetBondBetweenAtoms(match[1], match[2])
    if bond is None:
        return "unknown"
    if bond.IsInRing():
        sizes = [len(r) for r in mol.GetRingInfo().BondRings() if bond.GetIdx() in r]
        if sizes and min(sizes) < 8:
            return "cis"  # a double bond in a small ring is cis by construction
    stereo = bond.GetStereo()
    if stereo in (Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOTRANS):
        return "trans"
    if stereo in (Chem.BondStereo.STEREOZ, Chem.BondStereo.STEREOCIS):
        return "cis"
    return "unknown"


def _lowest_locants(positions: list[int]) -> tuple[int, ...]:
    if not positions:
        return ()
    best: tuple[int, ...] | None = None
    for start in positions:
        for direction in (1, -1):
            locants = tuple(sorted(((p - start) * direction) % 6 + 1 for p in positions))
            if best is None or locants < best:
                best = locants
    return best or ()


def vibration_names(found: list[FoundMotif]) -> frozenset[str]:
    """All library vibration names the found motifs can show."""
    return frozenset(name for f in found for name in f.vibrations)
