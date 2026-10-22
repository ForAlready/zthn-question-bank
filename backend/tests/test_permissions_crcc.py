"""一期角色权限映射单测。"""
from types import SimpleNamespace

from app.core.permissions import Permission, SubjectRole, can, permissions_for, ROLE_PERMISSIONS


def _user(*, is_superuser: bool = False, memberships=None):
    return SimpleNamespace(is_superuser=is_superuser, subject_memberships=memberships or [])


def _member(subject_id: int, role: str):
    return SimpleNamespace(subject_id=subject_id, role=role)


def test_admin_has_export_with_answers():
    admin = _user(is_superuser=True)
    assert can(admin, Permission.EXPORT_WITH_ANSWERS, subject_id=1)
    assert Permission.EXPORT_WITH_ANSWERS in permissions_for(admin, subject_id=1)


def test_editor_can_generate_but_not_export_answers():
    editor = _user(memberships=[_member(1, SubjectRole.EDITOR.value)])
    assert can(editor, Permission.GENERATE_PAPER, subject_id=1)
    assert can(editor, Permission.EXPORT_PAPER_WITHOUT_ANSWERS, subject_id=1)
    assert not can(editor, Permission.EXPORT_WITH_ANSWERS, subject_id=1)
    assert not can(editor, Permission.MANAGE_PAPER_TEMPLATE, subject_id=1)


def test_manager_can_manage_template_not_answers_by_default():
    manager = _user(memberships=[_member(1, SubjectRole.MANAGER.value)])
    assert can(manager, Permission.MANAGE_PAPER_TEMPLATE, subject_id=1)
    assert can(manager, Permission.GENERATE_PAPER, subject_id=1)
    assert not can(manager, Permission.EXPORT_WITH_ANSWERS, subject_id=1)


def test_viewer_readonly():
    viewer = _user(memberships=[_member(1, SubjectRole.VIEWER.value)])
    assert can(viewer, Permission.VIEW_QUESTION, subject_id=1)
    assert not can(viewer, Permission.GENERATE_PAPER, subject_id=1)
    assert ROLE_PERMISSIONS[SubjectRole.VIEWER] == frozenset({Permission.VIEW_QUESTION})


def test_no_membership_no_caps():
    user = _user()
    assert permissions_for(user, subject_id=1) == frozenset()
