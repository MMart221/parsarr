"""
Legacy webhook router — kept as an empty module so existing imports don't break
during the transition period. All routes live in parsarr/api/routes.py in v2.
"""
from fastapi import APIRouter

router = APIRouter()
