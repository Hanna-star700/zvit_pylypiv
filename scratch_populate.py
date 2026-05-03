import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'learncode.settings')
django.setup()

from courses.models import League

LEAGUES = [
    {"name": "Бронзова", "slug": "bronze", "icon": "🥉", "color": "#cd7f32", "order": 1},
    {"name": "Срібна", "slug": "silver", "icon": "🥈", "color": "#c0c0c0", "order": 2},
    {"name": "Золота", "slug": "gold", "icon": "🥇", "color": "#ffd700", "order": 3},
    {"name": "Сапфірова", "slug": "sapphire", "icon": "💎", "color": "#0f52ba", "order": 4},
    {"name": "Рубінова", "slug": "ruby", "icon": "🔴", "color": "#e0115f", "order": 5},
    {"name": "Смарагдова", "slug": "emerald", "icon": "🟩", "color": "#50c878", "order": 6},
    {"name": "Аметистова", "slug": "amethyst", "icon": "🟣", "color": "#9966cc", "order": 7},
    {"name": "Перлинна", "slug": "pearl", "icon": "⚪", "color": "#eae0c8", "order": 8},
    {"name": "Обсидіанова", "slug": "obsidian", "icon": "⬛", "color": "#4a4a4d", "order": 9},
    {"name": "Діамантова", "slug": "diamond", "icon": "🔷", "color": "#b9f2ff", "order": 10},
]

print("Populating leagues...")
League.objects.all().delete()
for l in LEAGUES:
    League.objects.create(**l)

print(f"Created {League.objects.count()} leagues.")
