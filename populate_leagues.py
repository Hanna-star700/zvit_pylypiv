import os
import sys
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "learncode.settings")
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from courses.models import GroupLeague, LeagueChallenge

# Ensure a superuser or generic user exists
admin, created = User.objects.get_or_create(username='admin', defaults={'email': 'admin@example.com'})
if created:
    admin.set_password('admin')
    admin.save()

# Create League 1
l1, _ = GroupLeague.objects.get_or_create(
    name='Клуб Пайтоністів',
    defaults={
        'description': 'Публічна ліга для всіх початківців та ентузіастів Python. Спілкуємось, розв\'язуємо задачі та підтримуємо один одного.',
        'is_public': True,
        'created_by': admin
    }
)
LeagueChallenge.objects.get_or_create(
    league=l1,
    title='Тижневий марафон',
    defaults={
        'description': 'Вирішити 50 завдань до кінця тижня',
        'goal_type': 'tasks',
        'target_value': 50,
        'start_date': timezone.now(),
        'end_date': timezone.now() + timezone.timedelta(days=7)
    }
)

# Create League 2
l2, _ = GroupLeague.objects.get_or_create(
    name='JS Ніндзя',
    defaults={
        'description': 'Ліга для тих, хто вивчає JavaScript. Приєднуйтесь, якщо хочете навчитись робити динамічні сайти.',
        'is_public': True,
        'created_by': admin
    }
)
LeagueChallenge.objects.get_or_create(
    league=l2,
    title='Головна ціль ліги',
    defaults={
        'description': 'Вирішити 30 завдань',
        'goal_type': 'tasks',
        'target_value': 30,
        'start_date': timezone.now(),
        'end_date': timezone.now() + timezone.timedelta(days=30)
    }
)

print("Created 2 public leagues.")
