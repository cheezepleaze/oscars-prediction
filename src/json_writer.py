from pathlib import Path
import json
from typing import Dict, Any


def write_json(data: Dict[str, Any], path: Path):
    """
    I/O: Writes Python dictionary to JSON.

    # TODO: Make sure this can take care of other awards systems and their respective data.
    """

    # create a folder if no folder exists
    path.parent.mkdir(parents = True, exist_ok = True)

    with path.open("w", encoding = "utf-8") as file:
        json.dump(
            data, file, indent = 2, ensure_ascii = False
        )