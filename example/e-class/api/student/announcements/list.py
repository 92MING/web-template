from eclass_api_base import EClassRoute


class StudentAnnouncementsListRoute(EClassRoute):
    Tags = "Student"

    async def get(self, page: int = 1, page_size: int = 10, class_id: str = "c1") -> dict[str, object]:
        rows = list(self.shared_dict.get(f"class:{class_id}:announcements", []))
        classroom = self._get_classrooms().get(class_id) or {}
        teacher_id = classroom.get("teacher_id")
        fallback_author = (self._get_users().get(teacher_id or "") or {}).get("nickname") or teacher_id
        announcements = [
            {
                "id": item.get("id") or f"a{index}",
                "title": item.get("title", ""),
                "content": item.get("content") or item.get("body") or "",
                "date": item.get("date") or item.get("created_at") or "",
                "author": item.get("author") or fallback_author,
            }
            for index, item in enumerate(rows, start=1)
            if isinstance(item, dict)
        ]
        total = len(announcements)
        start = (page - 1) * page_size
        end = start + page_size
        return {"announcements": announcements[start:end], "total": total, "page": page, "page_size": page_size}
