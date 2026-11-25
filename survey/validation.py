from collections.abc import Iterable

from survey.grid import Cell, CellClass, GridBounds, Point


class InvalidGrid(ValueError):
    pass


def validate_grid(bounds: GridBounds, cells: Iterable[object]) -> tuple[Cell, ...]:
    if not isinstance(bounds, GridBounds):
        raise InvalidGrid('expected a GridBounds value')
    try:
        records = iter(cells)
    except TypeError as exc:
        raise InvalidGrid('cell records must be iterable') from exc

    classified: dict[Point, CellClass] = {}
    for record in records:
        if not isinstance(record, (tuple, list)) or len(record) != 3:
            raise InvalidGrid('a cell requires x, y and a classification')
        x, y, raw_class = record
        if type(x) is not int or type(y) is not int:
            raise InvalidGrid('cell coordinates must be integers')
        if not bounds.contains(x, y):
            raise InvalidGrid(f'cell {(x, y)} is outside the tile')
        if not isinstance(raw_class, str):
            raise InvalidGrid(f'invalid classification at {(x, y)}')
        try:
            classification = CellClass(raw_class)
        except ValueError as exc:
            raise InvalidGrid(f'invalid classification at {(x, y)}') from exc
        previous = classified.setdefault((x, y), classification)
        if previous != classification:
            raise InvalidGrid(f'conflicting classifications at {(x, y)}')

    if len(classified) != bounds.area:
        raise InvalidGrid('classification does not cover every grid cell')
    return tuple((x, y, classified[x, y]) for x, y in bounds.coordinates())
