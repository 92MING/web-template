from eclass_api_base import EClassRoute


class StudentGradesOverviewRoute(EClassRoute):
    Tags = "Student"

    async def get(self, student_id: str = "s1") -> dict[str, object]:
        grades = self.shared_dict.get("student:grades", [
            {"course": "Python 基础", "score": 92, "max": 100},
            {"course": "Web 开发入门", "score": 85, "max": 100},
            {"course": "数据结构与算法", "score": 78, "max": 100},
            {"course": "数据库原理", "score": 88, "max": 100},
        ])
        avg = sum(g["score"] for g in grades) / len(grades) if grades else 0
        return {"grades": grades, "average": round(avg, 2)}
