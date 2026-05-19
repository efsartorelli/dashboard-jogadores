from dataclasses import dataclass
from datetime import date
import re


_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
BRAZILIAN_STATES = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
)


@dataclass(frozen=True)
class Submission:
    nickname: str
    data_referencia: date
    catches: int
    periodo_tipo: str = "mensal"
    state: str | None = None


def normalize_nickname(value: str) -> str:
    return sanitize_text(value, max_length=80)


def normalize_state(value: object) -> str:
    return sanitize_text(value, max_length=2).upper()


def sanitize_text(value: object, max_length: int) -> str:
    text = "" if value is None else str(value)
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("<", "").replace(">", "")
    text = _CONTROL_CHARS_RE.sub("", text)
    text = " ".join(text.strip().split())
    return text[:max_length]


def validate_submission(submission: Submission, previous_catches: int | None = None) -> list[str]:
    """Validate a player data submission before persistence.

    Returns a list of human-readable errors. Empty list means the payload is
    acceptable for insertion or moderation.
    """
    errors: list[str] = []
    nickname = normalize_nickname(submission.nickname)

    if not nickname:
        errors.append("Nickname é obrigatório.")
    if len(nickname) > 80:
        errors.append("Nickname deve ter no máximo 80 caracteres.")
    if not submission.state or not str(submission.state).strip():
        errors.append("Estado é obrigatório.")
    elif normalize_state(submission.state) not in BRAZILIAN_STATES:
        errors.append("Estado deve ser uma UF brasileira válida.")
    if submission.periodo_tipo not in {"mensal", "semanal"}:
        errors.append("Tipo de período deve ser mensal ou semanal.")
    if submission.catches <= 0:
        errors.append("Capturas totais devem ser maiores que zero.")
    if submission.catches > 9_999_999_999:
        errors.append("Capturas totais excedem o limite permitido.")
    if previous_catches is not None and submission.catches < previous_catches:
        errors.append("Capturas totais não podem ser menores que o registro anterior sem revisão manual.")
    if submission.data_referencia > date.today():
        errors.append("Data de referência não pode ser futura.")

    return errors
