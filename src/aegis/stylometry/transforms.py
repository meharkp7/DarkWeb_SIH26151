"""Adversarial text transformations (Phase 11, step 6).

Seven deterministic, dependency-free attacks used to measure how much
verification quality survives deliberate author camouflage:

=========================  ===================================================
transform                  effect
=========================  ===================================================
``punctuation_removal``    strips punctuation/symbol characters
``case_change``            swaps, uppercases, or lowercases letters
``slang_normalization``    replaces informal markers with formal wording
``paraphrase``             substitutes content words with synonyms
``translation``            glossary-based machine-translation stand-in
``shortening``             keeps only the leading part of the text
``noise``                  injects typos (deletes, swaps, substitutions)
=========================  ===================================================

Severity convention: ``0.0`` is the identity (the function returns the
input unchanged), ``1.0`` is the full-strength attack, and intermediate
values transform a seeded, reproducible *fraction* of the eligible
units — which is what makes a graded robustness curve possible.
Everything is deterministic for a fixed ``(text, severity, seed)``.

The slang, paraphrase, and translation lexicons are small built-in
glossaries: they are stand-ins for real normalization/translation
services (no third-party ML dependencies are permitted), chosen to
cover the informal markers and marketplace vocabulary the synthetic
corpus contains.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Literal

from aegis.stylometry.ngrams import DEFAULT_EMBEDDING_SEED

TransformName = Literal[
    "punctuation_removal",
    "case_change",
    "slang_normalization",
    "paraphrase",
    "translation",
    "shortening",
    "noise",
]

#: Every transform the plan requires, in plan order.
TRANSFORM_NAMES: tuple[TransformName, ...] = (
    "punctuation_removal",
    "case_change",
    "slang_normalization",
    "paraphrase",
    "translation",
    "shortening",
    "noise",
)

CaseMode = Literal["swap", "upper", "lower"]
TranslationLanguage = Literal["ru", "de", "fr", "es"]

#: Informal marker -> formal wording.
DEFAULT_SLANG: dict[str, tuple[str, ...]] = {
    "tbh": ("honestly",),
    "imo": ("in my opinion",),
    "imho": ("in my humble opinion",),
    "lol": ("haha",),
    "fyi": ("for your information",),
    "asap": ("promptly",),
    "nb.": ("note:",),
    "regards,": ("sincerely,",),
    "net": ("network",),
    "btw": ("by the way",),
    "thx": ("thanks",),
    "pls": ("please",),
    "gonna": ("going to",),
    "wanna": ("want to",),
    "kinda": ("somewhat",),
    "cuz": ("because",),
    "yall": ("you all",),
}

#: Content word -> paraphrase candidates (picked with the seeded RNG).
DEFAULT_PARAPHRASES: dict[str, tuple[str, ...]] = {
    "update": ("revision", "post"),
    "fees": ("charges", "tariff"),
    "stay": ("remain", "hold"),
    "fixed": ("unchanged", "steady"),
    "rotation": ("cycling", "refresh"),
    "listing": ("entry", "advert"),
    "vendor": ("supplier", "merchant"),
    "wallet": ("purse", "vault"),
    "session": ("login", "connection"),
    "mirror": ("proxy", "clone"),
    "reviews": ("ratings", "feedback"),
    "shipping": ("delivery", "dispatch"),
    "leak": ("exposure", "breach"),
    "bounty": ("reward", "prize"),
    "dump": ("export", "extract"),
    "escrow": ("trust", "brokerage"),
    "invites": ("invitations", "access codes"),
    "update:": ("revision:", "post:"),
}

#: English -> target language glossary used by the translation attack.
DEFAULT_TRANSLATIONS: dict[TranslationLanguage, dict[str, tuple[str, ...]]] = {
    "de": {
        "the": ("der", "die"),
        "update": ("Aktualisierung",),
        "fees": ("Gebühren",),
        "stay": ("bleiben",),
        "fixed": ("fest",),
        "rotation": ("Rotation",),
        "asap": ("sofort",),
        "listing": ("Anzeige",),
        "vendor": ("Händler",),
        "wallet": ("Brieftasche",),
        "session": ("Sitzung",),
        "mirror": ("Proxy",),
        "reviews": ("Bewertungen",),
        "shipping": ("Versand",),
        "leak": ("Leck",),
        "bounty": ("Prämie",),
        "dump": ("Abzug",),
        "escrow": ("Treuhänder",),
        "invites": ("Einladungen",),
        "and": ("und",),
        "of": ("von",),
        "to": ("zu",),
        "for": ("für",),
        "with": ("mit",),
        "will": ("wird",),
        "is": ("ist",),
        "this": ("dieses",),
    },
    "es": {
        "the": ("el", "la"),
        "update": ("actualización",),
        "fees": ("comisiones",),
        "stay": ("permanecer",),
        "fixed": ("fijo",),
        "rotation": ("rotación",),
        "asap": ("cuanto antes",),
        "listing": ("anuncio",),
        "vendor": ("vendedor",),
        "wallet": ("cartera",),
        "session": ("sesión",),
        "mirror": ("espejo",),
        "reviews": ("reseñas",),
        "shipping": ("envío",),
        "leak": ("filtración",),
        "bounty": ("recompensa",),
        "dump": ("volcado",),
        "escrow": ("depósito",),
        "invites": ("invitaciones",),
        "and": ("y",),
        "of": ("de",),
        "to": ("a",),
        "for": ("para",),
        "with": ("con",),
        "will": ("será",),
        "is": ("es",),
        "this": ("este",),
    },
    "fr": {
        "the": ("le", "la"),
        "update": ("mise à jour",),
        "fees": ("frais",),
        "stay": ("rester",),
        "fixed": ("fixe",),
        "rotation": ("rotation",),
        "asap": ("au plus vite",),
        "listing": ("annonce",),
        "vendor": ("vendeur",),
        "wallet": ("portefeuille",),
        "session": ("session",),
        "mirror": ("miroir",),
        "reviews": ("avis",),
        "shipping": ("expédition",),
        "leak": ("fuite",),
        "bounty": ("récompense",),
        "dump": ("vidage",),
        "escrow": ("séquestre",),
        "invites": ("invitations",),
        "and": ("et",),
        "of": ("de",),
        "to": ("à",),
        "for": ("pour",),
        "with": ("avec",),
        "will": ("sera",),
        "is": ("est",),
        "this": ("ce",),
    },
    "ru": {
        "the": ("тот",),
        "update": ("обновление",),
        "fees": ("сборы",),
        "stay": ("оставаться",),
        "fixed": ("фиксированный",),
        "rotation": ("ротация",),
        "asap": ("срочно",),
        "listing": ("объявление",),
        "vendor": ("продавец",),
        "wallet": ("кошелёк",),
        "session": ("сессия",),
        "mirror": ("зеркало",),
        "reviews": ("отзывы",),
        "shipping": ("доставка",),
        "leak": ("утечка",),
        "bounty": ("награда",),
        "dump": ("дамп",),
        "escrow": ("брокераж",),
        "invites": ("приглашения",),
        "and": ("и",),
        "of": ("из",),
        "to": ("в",),
        "for": ("для",),
        "with": ("с",),
        "will": ("будет",),
        "is": ("является",),
        "this": ("этот",),
    },
}

#: Maximum fraction of characters corrupted at ``severity == 1.0``.
NOISE_MAX_RATE = 0.2

#: Fraction of the text removed at ``severity == 1.0`` by shortening.
SHORTEN_MAX_DROP = 0.75

_KEYBOARD_NEIGHBORS: dict[str, str] = {
    "a": "sq",
    "b": "vgh",
    "c": "xdf",
    "d": "sfec",
    "e": "wrds",
    "f": "drgv",
    "g": "fhtb",
    "h": "gjyn",
    "i": "ujko",
    "j": "hkui",
    "k": "jloi",
    "l": "kop",
    "m": "njk",
    "n": "bhjm",
    "o": "ipl",
    "p": "ol",
    "q": "wa",
    "r": "edft",
    "s": "awedx",
    "t": "rfgy",
    "u": "yihj",
    "v": "cfgb",
    "w": "qase",
    "x": "zsdc",
    "y": "tugh",
    "z": "asx",
}


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith(("P", "S"))


def _normalize_lexicon(lexicon: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    return {key.lower(): tuple(values) for key, values in lexicon.items() if values}


def _substitute(
    text: str,
    lexicon: Mapping[str, Sequence[str]],
    severity: float,
    seed: int,
) -> str:
    """Word-boundary-safe, seeded, fraction-controlled substitution."""
    if severity <= 0.0 or not text:
        return text
    normalized = _normalize_lexicon(lexicon)
    if not normalized:
        return text
    keys = sorted(normalized, key=len, reverse=True)
    pattern = re.compile(
        rf"(?<!\w)(?:{'|'.join(re.escape(key) for key in keys)})(?!\w)",
        re.IGNORECASE,
    )
    rng = random.Random(seed)

    def replace(match: re.Match[str]) -> str:
        if severity < 1.0 and rng.random() >= severity:
            return match.group(0)
        options = normalized.get(match.group(0).lower())
        if not options:
            return match.group(0)
        return rng.choice(options)

    return pattern.sub(replace, text)


def remove_punctuation(text: str, *, severity: float = 1.0, seed: int = 0) -> str:
    """Drop punctuation and symbol characters (fraction at severity < 1).

    Removes Unicode punctuation *and* symbol characters (so emoticons
    such as ``:-)`` die too), then collapses the leftover runs of
    spaces/tabs.
    """
    if severity <= 0.0:
        return text
    rng = random.Random(seed)
    kept = [
        char
        for char in text
        if not (_is_punctuation(char) and (severity >= 1.0 or rng.random() < severity))
    ]
    return re.sub(r"[ \t]{2,}", " ", "".join(kept))


def change_case(
    text: str,
    *,
    severity: float = 1.0,
    seed: int = 0,
    mode: CaseMode = "swap",
) -> str:
    """Alter the case of a seeded fraction of letters.

    Modes: ``swap`` toggles each letter's case (``THis``), ``upper``
    uppercases, ``lower`` lowercases. Non-letters are untouched.
    """
    if severity <= 0.0:
        return text
    if mode not in {"swap", "upper", "lower"}:  # pragma: no cover - Literal guard
        raise ValueError(f"unknown case mode: {mode!r}")
    rng = random.Random(seed)
    output: list[str] = []
    for char in text:
        if char.isalpha() and (severity >= 1.0 or rng.random() < severity):
            if mode == "swap":
                output.append(char.swapcase())
            elif mode == "upper":
                output.append(char.upper())
            else:
                output.append(char.lower())
        else:
            output.append(char)
    return "".join(output)


def normalize_slang(
    text: str,
    *,
    severity: float = 1.0,
    seed: int = 0,
    lexicon: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """Replace informal markers with formal wording (slang lexicon)."""
    return _substitute(text, lexicon if lexicon is not None else DEFAULT_SLANG, severity, seed)


def paraphrase(
    text: str,
    *,
    severity: float = 1.0,
    seed: int = 0,
    lexicon: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """Substitute content words with seeded synonym choices."""
    return _substitute(
        text,
        lexicon if lexicon is not None else DEFAULT_PARAPHRASES,
        severity,
        seed,
    )


def translate(
    text: str,
    *,
    language: TranslationLanguage = "de",
    severity: float = 1.0,
    seed: int = 0,
) -> str:
    """Glossary-based translation stand-in.

    Known English words (function words, marketplace vocabulary, and
    informal markers) are replaced with their target-language
    equivalents; unknown words pass through unchanged. This mimics the
    *stylistic* effect of machine translation — markers and function
    words change surface form — without pulling in a translation
    model, which the dependency policy forbids.
    """
    glossary = DEFAULT_TRANSLATIONS.get(language)
    if glossary is None:
        raise ValueError(f"unsupported translation language: {language!r}")
    return _substitute(text, glossary, severity, seed)


def shorten(text: str, *, severity: float = 1.0) -> str:
    """Keep only the leading ``(1 - 0.75 * severity)`` fraction of words."""
    if severity <= 0.0:
        return text
    words = text.split()
    if not words:
        return text
    keep_ratio = 1.0 - SHORTEN_MAX_DROP * min(severity, 1.0)
    keep_count = max(1, round(len(words) * keep_ratio))
    return " ".join(words[:keep_count])


def add_noise(text: str, *, severity: float = 1.0, seed: int = 0) -> str:
    """Inject typos into a seeded fraction of characters.

    Up to ``NOISE_MAX_RATE * severity`` of non-whitespace characters are
    corrupted with one of: deletion, transposition with the next
    character, or substitution by a QWERTY keyboard neighbor of the
    same case.
    """
    if severity <= 0.0:
        return text
    rng = random.Random(seed)
    rate = NOISE_MAX_RATE * min(severity, 1.0)
    output: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace() or rng.random() >= rate:
            output.append(char)
            index += 1
            continue
        operation = rng.random()
        if operation < 0.34:
            index += 1  # deletion
        elif operation < 0.67 and index + 1 < len(text):
            output.append(text[index + 1])
            output.append(char)
            index += 2  # transposition
        else:
            output.append(_neighbor(char, rng))
            index += 1
    return "".join(output)


def _neighbor(char: str, rng: random.Random) -> str:
    lowered = char.lower()
    options = _KEYBOARD_NEIGHBORS.get(lowered)
    if not options:
        return char
    replacement = rng.choice(options)
    return replacement.upper() if char.isupper() else replacement


def apply_transform(
    text: str,
    name: TransformName,
    *,
    severity: float = 1.0,
    seed: int = DEFAULT_EMBEDDING_SEED,
) -> str:
    """Apply the named adversarial transform with a uniform severity.

    Args:
        text: Input text.
        name: One of :data:`TRANSFORM_NAMES`.
        severity: ``0.0`` returns *text* unchanged; ``1.0`` applies the
            transform at full strength.
        seed: RNG seed for the stochastic transforms.

    Raises:
        ValueError: If *name* is unknown or severity is out of range.
    """
    if name not in TRANSFORM_NAMES:
        raise ValueError(f"unknown transform {name!r}; expected one of {TRANSFORM_NAMES}")
    if not 0.0 <= severity <= 1.0:
        raise ValueError(f"severity must be within [0, 1], got {severity}")
    if severity == 0.0:
        return text
    if name == "punctuation_removal":
        return remove_punctuation(text, severity=severity, seed=seed)
    if name == "case_change":
        return change_case(text, severity=severity, seed=seed)
    if name == "slang_normalization":
        return normalize_slang(text, severity=severity, seed=seed)
    if name == "paraphrase":
        return paraphrase(text, severity=severity, seed=seed)
    if name == "translation":
        return translate(text, severity=severity, seed=seed)
    if name == "shortening":
        return shorten(text, severity=severity)
    return add_noise(text, severity=severity, seed=seed)
