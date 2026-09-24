import os
from typing import Any

import anaplan_sdk

from sm_epm.lib.anaplan.errors import SERVICE, anaplan_errors
from sm_epm.lib.env import load_env
from sm_epm.lib.errors import ConfigurationError

REQUIRED_ENV = ('ANAPLAN_USER_EMAIL', 'ANAPLAN_PASSWORD')


@anaplan_errors
def client_from_env(**kwargs: Any) -> anaplan_sdk.Client:
    """Build a basic-auth Anaplan client from ``ANAPLAN_*`` variables in the environment or ``.env``.

    Raises:
        ConfigurationError: a required variable is missing.
    """
    load_env()
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise ConfigurationError(f'{", ".join(missing)} not set in the environment or .env', service=SERVICE)
    return anaplan_sdk.Client(
        user_email=os.environ['ANAPLAN_USER_EMAIL'],
        password=os.environ['ANAPLAN_PASSWORD'],
        workspace_id=os.environ.get('ANAPLAN_WORKSPACE_ID') or None,
        model_id=os.environ.get('ANAPLAN_MODEL_ID') or None,
        **kwargs,
    )
