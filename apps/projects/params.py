"""Request params: a JSON body is read as if wrapped under the resource key, which must hold one
non-empty object whose permitted keys are read; a path id is cast by its leading digits."""

import re
from collections.abc import Mapping

from django.http import QueryDict

from apps.common.exceptions import ParameterMissing

_LEADING_INTEGER = re.compile(r"\s*([+-]?\d+(?:_\d+)*)", re.ASCII)
_DROPPED = object()


def _string(value):
    """A permitted scalar becomes its text (booleans `"t"` / `"f"`); arrays and objects are not
    permitted scalars, so they come back as `_DROPPED`."""
    match value:
        case None | str():
            return value
        case bool():
            return "t" if value else "f"
        case int() | float():
            return str(value)
    return _DROPPED


def permitted(request, key, model, names):
    """The `names` read from the object under `key`, which is required; a JSON object body that
    lacks `key` is first wrapped under it, keeping only `model`'s column names."""
    data = request.data
    if isinstance(data, Mapping) and not isinstance(data, QueryDict) and key not in data:
        columns = {field.attname for field in model._meta.concrete_fields}
        data = {key: {name: value for name, value in data.items() if name in columns}}
    params = data.get(key) if isinstance(data, Mapping) else None
    if not isinstance(params, Mapping) or not params:
        raise ParameterMissing()
    values = {name: _string(params[name]) for name in names if name in params}
    return {name: value for name, value in values.items() if value is not _DROPPED}


def record_id(raw):
    """A path id read by its leading digits: `5abc` is 5, and no leading digits is 0."""
    match = _LEADING_INTEGER.match(raw)
    return int(match.group(1)) if match else 0
