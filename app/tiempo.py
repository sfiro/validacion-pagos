from datetime import datetime, timedelta, timezone

COLOMBIA = timezone(timedelta(hours=-5), "COT")  # Colombia no tiene horario de verano


def ahora() -> datetime:
    return datetime.now(COLOMBIA)
