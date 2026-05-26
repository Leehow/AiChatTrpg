"""Culturally diverse name inspiration for TRPG guide conversations.

This module fights the common failure mode where Chinese-language character
creation prompts make the model default every generated PC to stock Chinese
names. The player's chat language should control narration language, not the
character's ethnicity, homeland, or naming style.

Scope note: these helpers are for setup/guide dialogue only. Final character
card JSON generation should preserve whatever the setup conversation already
settled, not receive a second naming-policy injection.
"""

from __future__ import annotations

import random
import secrets
from typing import List, Tuple


# Each entry: (culture_id, prompt_description). Examples are style seeds, not
# a menu for the model to copy verbatim.
CULTURE_HINTS: List[Tuple[str, str]] = [
    (
        "anglo_american",
        "Anglo-American (US / UK / Canada / Australia). Example surnames: "
        "Ashworth, Caldwell, Whitlock, Fairchild, Hollister. Example given "
        "names: Ethan, Margaret, Silas, Harriet, Everett.",
    ),
    (
        "slavic",
        "Slavic (Russian, Polish, Ukrainian, Czech, Serbian). Example "
        "surnames: Volkov, Nowak, Kaczmarek, Dvorak, Petrovic. Example "
        "given names: Dmitri, Katarzyna, Mikhail, Zofia, Stanislav.",
    ),
    (
        "germanic",
        "Germanic (German, Austrian, Swiss, Dutch). Example surnames: "
        "Richter, Baumann, Hoffmann, Seidel, van der Berg. Example given "
        "names: Klaus, Helga, Matthias, Ingrid, Wilhelm.",
    ),
    (
        "french",
        "French. Example surnames: Dubois, Lefevre, Marchand, Garnier, "
        "Chevalier. Example given names: Lucien, Amelie, Etienne, "
        "Clemence, Thibault.",
    ),
    (
        "italian",
        "Italian. Example surnames: Ricci, Conti, Moretti, Bianchi, "
        "Esposito. Example given names: Lorenzo, Giulia, Matteo, "
        "Eleonora, Salvatore.",
    ),
    (
        "iberian",
        "Spanish and Portuguese. Example surnames: Herrera, Castillo, "
        "Sousa, Ferreira, Vasquez. Example given names: Sofia, Rafael, "
        "Mariana, Diogo, Alejandro.",
    ),
    (
        "nordic",
        "Nordic (Swedish, Norwegian, Danish, Finnish, Icelandic). Example "
        "surnames: Lindqvist, Halvorsen, Eriksen, Virtanen, Sigurdsson. "
        "Example given names: Astrid, Erik, Sigrid, Mikko, Bjorn.",
    ),
    (
        "japanese",
        "Japanese. Romanized example surnames: Saeki, Kiriu, Takatori, "
        "Fujisawa, Hanazawa. Romanized example given names: Masato, "
        "Misaki, Ren, Chihiro, Kaede. When the conversation language uses "
        "kanji or hanzi, output the name in kanji form.",
    ),
    (
        "korean",
        "Korean. Romanized example surnames: Choi, Park, Yoon, Seo, Kang. "
        "Romanized example given names: Ji-hoon, Min-ji, Ji-ho, Soo-yeon, "
        "Tae-yang. Prefer hangul for the canonical name if you know the "
        "standard spelling; otherwise use the romanized form.",
    ),
    (
        "south_asian",
        "South Asian (Indian, Pakistani, Bangladeshi, Sri Lankan, Nepali). "
        "Example surnames: Mehta, Nair, Siddiqui, Iyer, Bandara. Example "
        "given names: Arjun, Priya, Rohan, Meera, Anika.",
    ),
    (
        "middle_eastern",
        "Middle Eastern (Arabic, Persian, Turkish, Levantine). Example "
        "surnames: al-Saleh, Darvish, Karakaya, Hadid, Najafi. Example "
        "given names: Farid, Zahra, Yusuf, Leila, Omar.",
    ),
    (
        "latin_american",
        "Latin American (Mexican, Brazilian, Argentinian, Colombian, "
        "Chilean). Example surnames: Mendoza, Vargas, Oliveira, Ramirez, "
        "Castellanos. Example given names: Rafael, Camila, Mateo, "
        "Valentina, Joaquin.",
    ),
    (
        "west_african",
        "West African (Ghanaian, Nigerian, Senegalese, Ivorian). Example "
        "surnames: Adjei, Okafor, Diallo, Mensah, Achebe. Example given "
        "names: Kwame, Nia, Chukwuma, Amara, Ayodele.",
    ),
    (
        "east_african",
        "East and Horn African (Ethiopian, Kenyan, Somali, Tanzanian). "
        "Example surnames: Tadesse, Wanjiru, Farah, Girma, Okello. Example "
        "given names: Yonas, Amani, Selamawit, Abdi, Neema.",
    ),
    (
        "jewish_ashkenazi",
        "Jewish Ashkenazi diaspora. Example surnames: Rosenbaum, Lieberman, "
        "Feldman, Ackermann, Abramowitz. Example given names: Miriam, Ezra, "
        "Yael, Asher, Hannah.",
    ),
    (
        "chinese_regional",
        "Chinese - use ONLY when this culture slot is assigned to the "
        "character. Vary regional feel: Jiangnan literati, northern rugged, "
        "Lingnan coastal, Sichuan / Chongqing, Hakka diaspora, northeastern. "
        "Avoid stock LLM defaults such as Li Ming, Zhang Wei, Wang Fang, Chen "
        "Jing, Chen Mo, Lin Xia, Su Qing, Gu Yan, Shen Qing, Lu Chen, Jiang "
        "Li, Xu Mo, Lin Shen, Bai Ye, Ye Bai, Chu He, Wen Yan.",
    ),
]


_FORBIDDEN_CN_NAMES = (
    "Li Ming, Zhang Wei, Wang Fang, Chen Jing, Chen Mo, Lin Xia, Su Qing, "
    "Gu Yan, Shen Qing, Lu Chen, Jiang Li, Xu Mo, Lin Shen, Bai Ye, Ye Bai, "
    "Chu He, Wen Yan, Shen Zhiyan, Gu Qiushan, Han Yue, Jiang Nian, Lin Mo"
)


def sample_culture_plan(count: int) -> List[Tuple[str, str]]:
    if count <= 0:
        return []
    return random.sample(CULTURE_HINTS, k=min(count, len(CULTURE_HINTS)))


def format_culture_plan(plan: List[Tuple[str, str]]) -> str:
    return "\n".join(f"{i}. {desc}" for i, (_id, desc) in enumerate(plan, 1))


def pick_single_culture_hint() -> str:
    _id, desc = random.choice(CULTURE_HINTS)
    return desc


def make_generation_nonce() -> str:
    return secrets.token_hex(4)


def build_batch_culture_rules(
    count: int = 3,
    *,
    target_language: str = "the player's selected language",
) -> str:
    plan = sample_culture_plan(count)
    return (
        "## Guide Dialogue Nudge: Candidate Name & Cultural Origin\n"
        f"You are about to propose {count} candidate characters. They MUST feel "
        "like real people from VISIBLY DIFFERENT cultural backgrounds, not a "
        "homogeneous batch of stock Chinese names. Below is a per-turn "
        "assignment plan. Example names are seeds; invent NEW names in the same "
        "cultural style, never copy the examples verbatim.\n\n"
        f"{format_culture_plan(plan)}\n\n"
        "How to apply:\n"
        f"- Character 1 uses origin 1, character 2 uses origin 2, ..., character {count} uses origin {count}.\n"
        "- Each character's CANONICAL name must be in its authentic native "
        "script: Latin alphabet for European names, kanji for Japanese, hangul "
        "for Korean, Arabic script for Arabic, hanzi for Chinese. NEVER replace "
        "the authentic name with a Chinese transliteration as the stored or "
        "primary name.\n"
        "- In guide dialogue, the FIRST narrative introduction of each "
        f"cross-language name MUST be readable in {target_language}: write a "
        "natural phonetic rendering in that language, followed by the original "
        "name in square brackets, e.g. Chinese target: "
        "西格妮·哈尔沃丝达特[Signe Halvorsdatter]; English target for Japanese: "
        "Kaede Takatori[高取楓]; Japanese target for Latin: "
        "シグネ・ハルヴォルスダッテル[Signe Halvorsdatter]. The bracketed "
        "original remains canonical.\n"
        "- Weave the cultural origin subtly into the backstory: hometown, "
        "heritage, family language, diaspora story, religion, class background.\n"
        "- Vary name lengths, etymological origins, and sound profiles across "
        "the candidates. A batch where every character has a two-syllable "
        "Chinese-sounding name is a failure.\n"
        "- If the world setting is explicitly mono-cultural, you may override "
        "the plan, but you must still vary region, dialect, class, ethnic "
        "minority, or era within that culture.\n"
        "- ABSOLUTELY FORBIDDEN: defaulting all or most candidates to Chinese "
        "names just because the conversation language is Chinese.\n"
        f"- FORBIDDEN stock Chinese names: {_FORBIDDEN_CN_NAMES}.\n"
        "- FORBIDDEN stock English names: John Smith, Jane Doe, Alex Chen, Jack Wilson."
    )


def build_single_culture_rule(
    *,
    target_language: str = "the player's selected language",
) -> str:
    return (
        "## Guide Dialogue Nudge: Suggested Cultural Origin\n"
        "Unless the player has already committed to a specific cultural "
        "background or name, use this origin as the starting point. Invent a NEW "
        "name in this style; do not copy the example seeds verbatim:\n\n"
        f"{pick_single_culture_hint()}\n\n"
        "- The character's CANONICAL name must be in its authentic native "
        "script: Latin alphabet for European names, kanji for Japanese, hangul "
        "for Korean, hanzi for Chinese. NEVER replace the authentic name with a "
        "Chinese transliteration as the stored or primary name.\n"
        "- In guide dialogue, the FIRST narrative introduction of a "
        f"cross-language name MUST be readable in {target_language}: write a "
        "natural phonetic rendering in that language, followed by the original "
        "name in square brackets, e.g. Chinese target: "
        "西格妮·哈尔沃丝达特[Signe Halvorsdatter]; English target for Japanese: "
        "Kaede Takatori[高取楓]; Japanese target for Latin: "
        "シグネ・ハルヴォルスダッテル[Signe Halvorsdatter]. The bracketed "
        "original remains canonical.\n"
        "- If the world setting is explicitly mono-cultural in a way that makes "
        "this origin absurd, pick a name that fits the setting instead.\n"
        "- ABSOLUTELY FORBIDDEN: defaulting to a Chinese name just because the "
        "conversation language is Chinese.\n"
        f"- FORBIDDEN stock names: {_FORBIDDEN_CN_NAMES}."
    )


def build_uncommitted_name_guidance(
    *,
    target_language: str = "the player's selected language",
) -> str:
    """Nudge for setup turns where the PC has no player-specified name yet.

    The guide may ask for a name/cultural background, or, if the player has
    asked the guide to decide, use the sampled origin as a concrete suggestion.
    """
    return (
        "## Guide Dialogue Nudge: Uncommitted Character Name\n"
        "The player has not clearly committed to a character name in their own "
        "words. Do not default to a stock Chinese name just because the "
        "conversation is Chinese. If you are still interviewing the player, ask "
        "for a name/cultural background or offer to recommend one. If the player "
        "asks you to recommend, fill, auto-generate, or decide the name, use a "
        "multicultural origin that fits the world and character concept.\n\n"
        + build_single_culture_rule(target_language=target_language)
    )
