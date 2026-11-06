"""Owned high-rarity characters and weapons; first copy is stage zero."""
from dataclasses import dataclass
from .models import Item


def collectible(item):
    return item.rarity in (4, 5) and item.id.startswith(('char:', 'weapon:'))


def owner_id(item):
    if item.id.startswith('char:'):
        return item.id
    return 'char:' + item.id.partition(':')[2].split('-weapon', 1)[0]


@dataclass(frozen=True)
class OwnedItem:
    item: Item
    copies: int

    @property
    def level(self):
        return min(6, max(0, self.copies - 1))

    @property
    def maxed(self):
        return self.level == 6

    @property
    def label(self):
        return '意识' if self.item.id.startswith('char:') else '进化'

    @property
    def owner(self):
        return owner_id(self.item)
