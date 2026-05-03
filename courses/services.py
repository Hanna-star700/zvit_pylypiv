# -*- coding: utf-8 -*-
"""Сервіс гейміфікації: бали, вогник, ліги, досягнення."""
from datetime import date, timedelta, datetime
from django.db.models import Sum, F

from .models import (
    GameProfile, League, Achievement, UserAchievement,
    UserProgress, QuizAttempt, DailyStudyTime, AILessonQuizAttempt,
    GroupLeague, GroupLeagueMember, LeagueChallenge
)


def get_player_id(request):
    """Повертає ідентифікатор гравця: session_key або user_id."""
    if request.user.is_authenticated:
        return None, request.user
    return request.session.session_key, None


def get_or_create_profile(request):
    """Отримати або створити ігровий профіль для поточного відвідувача."""
    session_key, user = get_player_id(request)
    if user:
        profile, _ = GameProfile.objects.get_or_create(user=user, defaults={'session_key': None})
    else:
        if not session_key:
            request.session.create()
            session_key = request.session.session_key
        profile, _ = GameProfile.objects.get_or_create(
            session_key=session_key,
            defaults={'user': None}
        )
    return profile


def update_league(profile):
    """Оновити лігу профілю за балами."""
    league = (
        League.objects.filter(min_points__lte=profile.points)
        .order_by('-min_points')
        .first()
    )
    if league and profile.league != league:
        profile.league = league
        profile.save(update_fields=['league'])


def update_streak(profile):
    """Оновити вогник: сьогодні активність — збільшити або зберегти streak."""
    today = date.today()
    if profile.last_activity_date is None:
        profile.streak_days = 1
        profile.last_activity_date = today
        profile.save(update_fields=['streak_days', 'last_activity_date'])
        return
    if profile.last_activity_date == today:
        return
    if profile.last_activity_date == today - timedelta(days=1):
        profile.streak_days += 1
    else:
        profile.streak_days = 1
    profile.last_activity_date = today
    profile.save(update_fields=['streak_days', 'last_activity_date'])


def add_points(profile, points, reason=''):
    """Додати бали та оновити лігу."""
    profile.points += points
    profile.save(update_fields=['points'])
    update_league(profile)

    if profile.user_id:
        GroupLeagueMember.objects.filter(user_id=profile.user_id).update(points=F('points') + points)


def count_completed_lessons(request):
    """Кількість завершених уроків для поточного гравця."""
    session_key, user = get_player_id(request)
    qs = UserProgress.objects.filter(completed=True)
    if user:
        qs = qs.filter(user=user)
    else:
        qs = qs.filter(session_key=session_key)
    return qs.count()


def count_completed_lessons_for_course(request, course):
    """Скільки уроків курсу завершено (для прогрес-бару)."""
    session_key, user = get_player_id(request)
    qs = UserProgress.objects.filter(completed=True, lesson__course=course)
    if user:
        qs = qs.filter(user=user)
    else:
        qs = qs.filter(session_key=session_key)
    return qs.count()


def add_study_time(request, minutes):
    """Додати хвилини навчання за сьогодні (тільки для залогінених)."""
    if not request.user.is_authenticated or minutes <= 0:
        return
    today = date.today()
    obj, _ = DailyStudyTime.objects.get_or_create(
        user=request.user, date=today,
        defaults={'minutes': 0}
    )
    obj.minutes += minutes
    obj.save(update_fields=['minutes'])


_WEEKDAY_UK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']


def get_weekly_study_time(request):
    """Повертає список (назва дня, хвилини) за останні 7 днів для профілю."""
    if not request.user.is_authenticated:
        return []
    today = date.today()
    days_back = [today - timedelta(days=i) for i in range(7)]
    qs = DailyStudyTime.objects.filter(
        user=request.user,
        date__in=days_back
    ).values_list('date', 'minutes')
    by_date = dict(qs)
    result = []
    for d in reversed(days_back):
        day_name = _WEEKDAY_UK[d.weekday()]
        result.append((day_name, by_date.get(d, 0)))
    return result


def count_quizzes_passed(request):
    """Кількість пройдених звичайних тестів (Quiz) для профілю."""
    if not request.user.is_authenticated:
        return 0
    return QuizAttempt.objects.filter(
        user=request.user,
        is_practice=False
    ).values('quiz').distinct().count()


def count_ai_quizzes_passed(request):
    """Кількість пройдених AI-тестів до уроків (унікальні lesson+question_type)."""
    if not request.user.is_authenticated:
        return 0
    from django.db.models import Count
    return AILessonQuizAttempt.objects.filter(
        user=request.user
    ).values('lesson', 'question_type').distinct().count()


def count_tests_passed(request):
    """Загальна кількість пройдених тестів (звичайні + AI) для досягнень."""
    return count_quizzes_passed(request) + count_ai_quizzes_passed(request)


def check_and_award_achievements(request, profile):
    """Перевірити умови досягнень та видати нові. Повертає список щойно отриманих досягнень [{name, icon, description}]."""
    earned_ids = set(
        UserAchievement.objects.filter(session_key=profile.session_key).values_list('achievement_id', flat=True)
    )
    if profile.user_id:
        earned_ids |= set(
            UserAchievement.objects.filter(user=profile.user).values_list('achievement_id', flat=True)
        )

    lessons_count = count_completed_lessons(request)
    tests_count = count_tests_passed(request)
    newly_awarded = []
    for ach in Achievement.objects.exclude(id__in=earned_ids):
        grant = False
        if ach.condition_type == 'first_lesson' and lessons_count >= 1:
            grant = True
        elif ach.condition_type == 'lessons_5' and lessons_count >= 5:
            grant = True
        elif ach.condition_type == 'lessons_10' and lessons_count >= 10:
            grant = True
        elif ach.condition_type == 'lessons_15' and lessons_count >= 15:
            grant = True
        elif ach.condition_type == 'first_quiz' and tests_count >= 1:
            grant = True
        elif ach.condition_type == 'quizzes_5' and tests_count >= 5:
            grant = True
        elif ach.condition_type == 'quizzes_10' and tests_count >= 10:
            grant = True
        elif ach.condition_type == 'quizzes_50' and tests_count >= 50:
            grant = True
        elif ach.condition_type == 'quizzes_100' and tests_count >= 100:
            grant = True
        elif ach.condition_type == 'streak_3' and profile.streak_days >= 3:
            grant = True
        elif ach.condition_type == 'streak_7' and profile.streak_days >= 7:
            grant = True
        elif ach.condition_type == 'streak_14' and profile.streak_days >= 14:
            grant = True
        elif ach.condition_type == 'points_100' and profile.points >= 100:
            grant = True
        elif ach.condition_type == 'points_500' and profile.points >= 500:
            grant = True
        elif ach.condition_type == 'points_1000' and profile.points >= 1000:
            grant = True
        if grant:
            UserAchievement.objects.get_or_create(
                achievement=ach,
                session_key=profile.session_key or None,
                user=profile.user,
                defaults={}
            )
            add_points(profile, ach.points_reward)
            newly_awarded.append({
                'name': ach.name,
                'icon': ach.icon or '🏆',
                'description': ach.description or '',
            })
    return newly_awarded


def award_lesson_complete(request, lesson):
    """Викликати після завершення уроку: бали + вогник + досягнення."""
    profile = get_or_create_profile(request)
    kw = {'lesson': lesson}
    if profile.user_id:
        kw['user'] = profile.user
        kw['session_key'] = None
    else:
        kw['user'] = None
        kw['session_key'] = profile.session_key
    progress, created = UserProgress.objects.get_or_create(defaults={'completed': False}, **kw)
    if progress.completed:
        return
    progress.completed = True
    progress.completed_at = datetime.now()
    progress.save()
    update_streak(profile)
    add_points(profile, 15)
    add_study_time(request, lesson.duration_minutes or 15)
    return check_and_award_achievements(request, profile)


def award_quiz_complete(request, quiz, score, max_score, is_practice):
    """Викликати після проходження тесту."""
    profile = get_or_create_profile(request)
    update_streak(profile)
    if not is_practice:
        add_study_time(request, 5)
    if not is_practice and score > 0:
        add_points(profile, score)
        if score == max_score:
            for ach in Achievement.objects.filter(condition_type='quiz_perfect'):
                UserAchievement.objects.get_or_create(
                    achievement=ach,
                    session_key=profile.session_key,
                    user=profile.user,
                    defaults={}
                )
                add_points(profile, ach.points_reward)
    return check_and_award_achievements(request, profile)


def get_leaderboard(limit=20):
    """Топ гравців за балами (по профілях з session_key або user)."""
    return (
        GameProfile.objects.filter(points__gt=0)
        .select_related('league')
        .order_by('-points')[:limit]
    )


def get_average_rating(course=None, lesson=None):
    """Середній рейтинг для курсу або уроку."""
    from .models import Rating
    from django.db.models import Avg
    qs = Rating.objects.filter(score__gte=1, score__lte=5)
    if course:
        qs = qs.filter(course=course)
    if lesson:
        qs = qs.filter(lesson=lesson)
    avg = qs.aggregate(a=Avg('score'))['a'] or 0
    return round(avg, 1), qs.count()
