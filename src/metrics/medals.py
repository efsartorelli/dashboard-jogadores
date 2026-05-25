from __future__ import annotations

from copy import deepcopy


_MEDAL_TITLES = [
    "Primeiro Marco",
    "Cacador Constante",
    "Rota em Movimento",
    "Ritmo de Captura",
    "Meia Lenda",
    "Jornada Forte",
    "Capturador Avancado",
    "Foco Total",
    "Quase Milhao",
    "Clube do Milhao",
    "Horizonte Prateado",
    "Rastro Consistente",
    "Pulso Competitivo",
    "Avanco Azul",
    "Sequencia Suprema",
    "Mestre de Rotas",
    "Radar Preciso",
    "Escalada Elite",
    "Guardiao do Ritmo",
    "Duplo Milhao",
    "Escudo Dourado",
    "Dominio de Campo",
    "Forca Ascendente",
    "Chama Competitiva",
    "Marco Lendario",
    "Trilha de Ouro",
    "Cacador Implacavel",
    "Auge Regional",
    "Elite Nacional",
    "Trinca Milionaria",
    "Brilho Esmeralda",
    "Estrela de Captura",
    "Diamante Vivo",
    "Coroa Suprema",
    "Lenda do Ranking",
]

_ICON_CYCLES = {
    "bronze": ["target", "map", "bolt", "radar", "spark", "orbit", "chart", "streak", "shine"],
    "silver": ["radar", "chart", "shield", "orbit", "star", "evolution", "spark", "crystal", "target", "bolt"],
    "gold": ["trophy", "flame", "shield", "chart", "crown", "streak", "radar", "star", "orbit", "shine"],
    "platinum": ["star", "diamond", "crown", "crystal", "evolution", "trophy"],
}


def _tier_for_threshold(threshold: int) -> tuple[str, str]:
    if threshold < 1_000_000:
        return "bronze", "circle"
    if threshold < 2_000_000:
        return "silver", "hexagon"
    if threshold < 3_000_000:
        return "gold", "shield"
    return "platinum", "diamond"


def build_capture_medals() -> list[dict]:
    medals = []
    tier_indexes: dict[str, int] = {}
    for index, title in enumerate(_MEDAL_TITLES, start=1):
        threshold = index * 100_000
        tier, shape_type = _tier_for_threshold(threshold)
        tier_index = tier_indexes.get(tier, 0)
        tier_indexes[tier] = tier_index + 1
        if tier == "platinum" and tier_index % 2 == 1:
            shape_type = "star"
        icons = _ICON_CYCLES[tier]
        medals.append({
            "threshold": threshold,
            "title": title,
            "tier": tier,
            "icon_type": icons[tier_index % len(icons)],
            "shape_type": shape_type,
        })
    return medals


CAPTURE_MEDALS = build_capture_medals()
CAPTURE_MEDAL_COUNT = len(CAPTURE_MEDALS)


def calculate_medal_progress(total_captures: int | float | None) -> dict:
    try:
        total = max(0, int(total_captures or 0))
    except (TypeError, ValueError):
        total = 0

    unlocked = [medal for medal in CAPTURE_MEDALS if total >= medal["threshold"]]
    unlocked_count = len(unlocked)
    next_medal = CAPTURE_MEDALS[unlocked_count] if unlocked_count < CAPTURE_MEDAL_COUNT else None
    previous_threshold = unlocked[-1]["threshold"] if unlocked else 0

    if next_medal:
        span = max(1, next_medal["threshold"] - previous_threshold)
        progress_pct = min(100, max(0, round(((total - previous_threshold) / span) * 100, 1)))
        missing = max(0, next_medal["threshold"] - total)
    else:
        progress_pct = 100
        missing = 0

    enriched = []
    for medal in CAPTURE_MEDALS:
        item = deepcopy(medal)
        if total >= item["threshold"]:
            item["status"] = "unlocked"
        elif next_medal and item["threshold"] == next_medal["threshold"]:
            item["status"] = "current"
        else:
            item["status"] = "locked"
        item["is_latest"] = bool(unlocked and item["threshold"] == unlocked[-1]["threshold"])
        enriched.append(item)

    return {
        "total_captures": total,
        "unlocked_count": unlocked_count,
        "total_count": CAPTURE_MEDAL_COUNT,
        "next_medal": deepcopy(next_medal) if next_medal else None,
        "missing_to_next": missing,
        "progress_pct": progress_pct,
        "medals": enriched,
    }
