import hashlib
import secrets
from fastapi import Request
from core.server import AdvanceRequest
from core.server.data_types.apikey import create_apikey
from core.utils.type_utils import AdvancedBaseModel

from eclass_api_base import EClassRoute, STUDENT_ROLE_NAME, TEACHER_ROLE_NAME


class RegisterRequest(AdvancedBaseModel):
    email: str
    nickname: str
    password: str
    role: str = "student"
    school_id: str = ""
    grade: str = ""


class LoginRequest(AdvancedBaseModel):
    email: str
    password: str


class EclassAuthRoute(EClassRoute):
    Tags = "E-Class"
    ApikeyProtected = False

    def _init_data(self):
        """Initialize default school, classrooms, test accounts if not exist."""
        # Schools
        schools = self.shared_data.get_shared_dict_value("eclass", "schools")
        if not schools:
            schools = {
                "school1": {"id": "school1", "name": "香港马料水职业技术学校"},
            }
            self.shared_data.set_shared_dict_value("eclass", "schools", schools)

        # Users (test accounts)
        users = self.shared_data.get_shared_dict_value("eclass", "users")
        if not users:
            users = {
                "student1": {
                    "user_id": "student1",
                    "email": "student1@example.com",
                    "nickname": "Student One",
                    "name": "Student One",
                    "role": "student",
                    "school_id": "school1",
                    "grade": "高一",
                    "password_hash": "8d969eef6ecad3c2",
                },
                "student2": {
                    "user_id": "student2",
                    "email": "student2@example.com",
                    "nickname": "Student Two",
                    "name": "Student Two",
                    "role": "student",
                    "school_id": "school1",
                    "grade": "高二",
                    "password_hash": "8d969eef6ecad3c2",
                },
                "teacher1": {
                    "user_id": "teacher1",
                    "email": "teacher1@example.com",
                    "nickname": "Teacher One",
                    "name": "Teacher One",
                    "role": "teacher",
                    "school_id": "school1",
                    "grade": "",
                    "password_hash": "8d969eef6ecad3c2",
                },
            }
            self.shared_data.set_shared_dict_value("eclass", "users", users)

        # Classrooms
        classrooms = self.shared_data.get_shared_dict_value("eclass", "classrooms")
        if classrooms is None:
            classrooms = {
                "c1": {
                    "id": "c1",
                    "name": "数学课 Class 1",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": ["student1", "student2"],
                },
                "c2": {
                    "id": "c2",
                    "name": "英语课 Class 2",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": ["student1"],
                },
                "c3": {
                    "id": "c3",
                    "name": "物理课 Class 3",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": [],
                },
            }
            self.shared_data.set_shared_dict_value("eclass", "classrooms", classrooms)

        # Default courses for c1
        courses_c1 = self.shared_data.get_shared_dict_value("eclass", "class:c1:courses")
        if courses_c1 is None:
            self.shared_data.set_shared_dict_value("eclass", "class:c1:courses", [
                {"id": "course-1", "title": "Python 基础", "description": "从零开始学习 Python 编程", "teacher": "Teacher One", "syllabus": ["变量与数据类型", "控制流", "函数", "面向对象"], "materials": [{"name": "第1章讲义", "url": "#"}, {"name": "第2章讲义", "url": "#"}], "enrolled_count": 2, "created_at": "2024-01-15"},
                {"id": "course-2", "title": "Web 开发入门", "description": "HTML、CSS、JavaScript 基础", "teacher": "Teacher One", "syllabus": ["HTML结构", "CSS样式", "JS交互", "DOM操作"], "materials": [{"name": "HTML参考", "url": "#"}], "enrolled_count": 2, "created_at": "2024-02-01"},
                {"id": "course-3", "title": "数据结构与算法", "description": "常用数据结构与算法解析", "teacher": "Teacher One", "syllabus": ["数组与链表", "栈与队列", "树", "排序算法"], "materials": [{"name": "算法导论", "url": "#"}], "enrolled_count": 1, "created_at": "2024-03-01"},
            ])

    def _get_users(self):
        self._init_data()
        return self.shared_data.get_shared_dict_value("eclass", "users") or {}

    def _get_schools(self):
        self._init_data()
        return self.shared_data.get_shared_dict_value("eclass", "schools") or {}

    def _get_classrooms(self):
        self._init_data()
        return self.shared_data.get_shared_dict_value("eclass", "classrooms") or {}

    def _hash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()[:16]

    def _normalize_role(self, role: str) -> str:
        return TEACHER_ROLE_NAME if str(role or "").strip().lower() == TEACHER_ROLE_NAME else STUDENT_ROLE_NAME

    async def _issue_apikey(self, *, user_id: str, role: str) -> str:
        await self.ensure_permission_roles()
        api_key = await create_apikey(
            user_id=user_id,
            role=[role],
            expire_seconds=86400,
            name=f"eclass:{user_id}",
        )
        return api_key.key

    async def post(self, request: Request, action: str = "login") -> dict[str, object]:
        if action == "register":
            body = await request.json()
            req = RegisterRequest(**body)
            users = self._get_users()
            # Check email uniqueness
            for u in users.values():
                if u.get("email") == req.email:
                    return {"ok": False, "error": "邮箱已注册", "error_code": "email_already_registered"}
            user_id = req.email.split("@")[0] + "_" + secrets.token_hex(4)
            role = self._normalize_role(req.role)
            users[user_id] = {
                "user_id": user_id,
                "email": req.email,
                "nickname": req.nickname,
                "name": req.nickname,
                "role": role,
                "school_id": req.school_id,
                "grade": req.grade if role == STUDENT_ROLE_NAME else "",
                "password_hash": self._hash(req.password),
            }
            self.shared_data.set_shared_dict_value("eclass", "users", users)
            token = await self._issue_apikey(user_id=user_id, role=role)
            return {"ok": True, "token": token, "user_id": user_id, "role": role}

        if action == "login":
            body = await request.json()
            req = LoginRequest(**body)
            users = self._get_users()
            # Find user by email
            user = None
            user_id = None
            for uid, u in users.items():
                if u.get("email") == req.email:
                    user = u
                    user_id = uid
                    break
            if not user or user.get("password_hash") != self._hash(req.password):
                return {"ok": False, "error": "邮箱或密码错误", "error_code": "invalid_credentials"}
            role = self._normalize_role(str(user.get("role") or STUDENT_ROLE_NAME))
            token = await self._issue_apikey(user_id=str(user_id or ""), role=role)
            return {"ok": True, "token": token, "user_id": user_id, "role": role}

        return {"ok": False, "error": "无效的操作", "error_code": "invalid_action"}

    async def get(self, request: Request, action: str = "me") -> dict[str, object]:
        if action == "me":
            user = await self.get_current_user(AdvanceRequest.Cast(request))
            if not user:
                return {"ok": False, "error": "未登录", "error_code": "not_logged_in"}
            return {"ok": True, "user": user}

        if action == "schools":
            schools = self._get_schools()
            return {"ok": True, "schools": list(schools.values())}

        if action == "test_accounts":
            return {"ok": True, "accounts": [
                {"role": "学生", "email": "student1@example.com", "password": "123456"},
                {"role": "学生", "email": "student2@example.com", "password": "123456"},
                {"role": "老师", "email": "teacher1@example.com", "password": "123456"},
            ]}

        return {"ok": False, "error": "无效的操作", "error_code": "invalid_action"}
