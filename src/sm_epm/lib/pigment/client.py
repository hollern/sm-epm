from pigment import PigmentClient, PigmentConfig

from sm_epm.lib.env import load_env
from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.pigment.errors import SERVICE


def client_from_env() -> PigmentClient:
    """Build a Pigment client from ``PIGMENT_*`` variables in the environment or ``.env``.

    Raises:
        ConfigurationError: ``PIGMENT_API_TOKEN`` is missing.
    """
    load_env()
    try:
        config = PigmentConfig.from_env()
    except ValueError as exc:
        raise ConfigurationError(f'{exc} (check .env)', service=SERVICE) from exc
    return PigmentClient(config)
