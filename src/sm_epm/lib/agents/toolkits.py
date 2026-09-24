"""Read-only Anaplan and Pigment tools for agents.

Nothing here writes to either system. The default Anaplan model is production, so a write tool
must be a deliberate addition in a specific agent, never part of these toolkits.
"""

from __future__ import annotations

from typing import Annotated

import anaplan_sdk
import pandas as pd
from pigment import PigmentClient
from pydantic import Field

from sm_epm.lib.agents.tools import tool
from sm_epm.lib.anaplan import client as anaplan_client
from sm_epm.lib.anaplan import data as anaplan_data
from sm_epm.lib.anaplan.errors import anaplan_errors
from sm_epm.lib.pigment import client as pigment_client
from sm_epm.lib.pigment import data as pigment_data
from sm_epm.lib.pigment.errors import pigment_errors


class AnaplanToolkit:
    """Browse and read one Anaplan model. The client is built from ``.env`` on first use unless
    one is passed."""

    def __init__(self, client: anaplan_sdk.Client | None = None) -> None:
        self._client = client

    @property
    def client(self) -> anaplan_sdk.Client:
        if self._client is None:
            self._client = anaplan_client.client_from_env()
        return self._client

    @tool
    def anaplan_list_modules(self) -> list:
        """List the modules in the Anaplan model, with their IDs."""
        with anaplan_errors:
            return self.client.tr.get_modules()

    @tool
    def anaplan_list_views(
        self, module_id: Annotated[int | None, Field(description='Only views of this module')] = None
    ) -> list:
        """List saved views in the Anaplan model, optionally for one module."""
        with anaplan_errors:
            views = self.client.tr.get_views()
        return [v for v in views if module_id is None or v.moduleId == module_id]

    @tool
    def anaplan_list_line_items(self, module_id: int) -> list:
        """List the line items of an Anaplan module, with their formulas and formats."""
        with anaplan_errors:
            return self.client.tr.get_line_items(only_module_id=module_id)

    @tool
    def anaplan_list_lists(self) -> list:
        """List the lists (dimensions) in the Anaplan model, with their IDs."""
        with anaplan_errors:
            return self.client.tr.get_lists()

    @tool
    def anaplan_list_exports(self) -> list:
        """List the bulk export actions in the Anaplan model, with their IDs and layouts."""
        with anaplan_errors:
            return self.client.get_exports()

    @tool
    def anaplan_read_view(
        self,
        view_id: Annotated[int, Field(description='A module ID, saved view ID or line item ID')],
        max_rows: Annotated[int | None, Field(description='Cap on data rows')] = 500,
        long: Annotated[bool, Field(description='One row per cell instead of the grid layout')] = False,
    ) -> pd.DataFrame:
        """Read the data in an Anaplan module or saved view, with its default page selection."""
        return anaplan_data.view_df(view_id, client=self.client, max_rows=max_rows, long=long)

    @tool
    def anaplan_read_list(self, list_id: int) -> pd.DataFrame:
        """Read every item in an Anaplan list, with codes, parents and properties."""
        return anaplan_data.list_items_df(list_id, client=self.client)

    @tool
    def anaplan_run_export(self, export_id: int) -> pd.DataFrame:
        """Run an Anaplan bulk export action and read its file. Exports don't change model data."""
        return anaplan_data.export_df(export_id, client=self.client)


class PigmentToolkit:
    """Browse and read Pigment applications. The client is built from ``.env`` on first use unless
    one is passed."""

    def __init__(self, client: PigmentClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> PigmentClient:
        if self._client is None:
            self._client = pigment_client.client_from_env()
        return self._client

    @tool
    def pigment_list_applications(self) -> list:
        """List the Pigment applications the API key can see, with their IDs."""
        with pigment_errors:
            return self.client.list_applications()

    @tool
    def pigment_list_blocks(self, application_id: str) -> list:
        """List the blocks (metrics, lists, tables) in a Pigment application, with IDs and types."""
        with pigment_errors:
            return self.client.list_blocks(application_id)

    @tool
    def pigment_list_views(self, application_id: str, block_id: str) -> list:
        """List the saved views of a Pigment block."""
        with pigment_errors:
            return self.client.list_views(application_id, block_id)

    @tool
    def pigment_read_view(self, view_id: str) -> pd.DataFrame:
        """Read a Pigment saved view, laid out as the view is."""
        return pigment_data.view_df(view_id, client=self.client)

    @tool
    def pigment_read_block(
        self,
        block_id: str,
        block_type: Annotated[
            str, Field(description='The type from pigment_list_blocks: DimensionList, TransactionList, Metric or Table')
        ],
    ) -> pd.DataFrame:
        """Read a Pigment block's raw data in flat form: dimension columns first, then values."""
        return pigment_data.block_df(block_id, block_type, client=self.client)
