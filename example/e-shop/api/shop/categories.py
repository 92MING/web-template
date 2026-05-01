from eshop_base import ShopRouteBase


class ShopCategoriesRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self) -> dict[str, object]:
        return {"categories": self._get_categories()}
