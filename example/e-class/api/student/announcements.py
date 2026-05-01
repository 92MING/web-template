from eclass_api_base import EClassRoute


class StudentAnnouncementsRoute(EClassRoute):
    Tags = "Student"

    async def get(self, class_id: str) -> dict[str, object]:
        return {"items": self.shared_dict.get(f"class:{class_id}:announcements", [])}
