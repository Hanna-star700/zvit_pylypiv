# -*- coding: utf-8 -*-
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib.auth import login
from django.utils import timezone
from urllib.parse import quote
import json

from django.db.models import Q
from .models import (
    Course, Lesson, Exercise, Quiz, Question, Rating,
    League, GameProfile, Achievement, UserAchievement, Competition, QuizAttempt,
    AIPracticeAttempt, PodcastConversation, GroupLeague, GroupLeagueMember, LeagueChallenge, LeagueMessage
)
from .ai_service import (
    generate_task as ai_generate_task,
    check_student_code as ai_check_code,
    parse_score_from_feedback,
    generate_placement_task,
    evaluate_placement_answer,
    generate_lesson_content,
    podcast_reply,
    generate_quiz_questions,
    evaluate_quiz_answers,
)
from .services import (
    get_or_create_profile, get_average_rating, get_leaderboard,
    award_lesson_complete, award_quiz_complete, count_completed_lessons,
    count_completed_lessons_for_course, get_weekly_study_time, count_quizzes_passed,
    add_points,
)
from .forms import RegisterForm, ProfileEditForm, GroupLeagueForm, LeagueChallengeForm, LeagueMessageForm



def page_not_found_view(request, exception=None):
    """Кастомна сторінка 404."""
    return render(request, '404.html', status=404)


def server_error_view(request):
    """Кастомна сторінка 500."""
    return render(request, '500.html', status=500)


def sitemap_view(request):
    """Простий sitemap.xml для пошукових систем."""
    base = request.build_absolute_uri('/')[:-1]
    urls = [base + '/', base + '/courses/', base + '/login/', base + '/register/']
    for course in Course.objects.filter(is_published=True):
        urls.append(base + reverse('course_detail', kwargs={'slug': course.slug}))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += '  <url><loc>{}</loc><changefreq>weekly</changefreq></url>\n'.format(url.replace('&', '&amp;'))
    xml += '</urlset>'
    return HttpResponse(xml, content_type='application/xml')


def robots_txt_view(request):
    """robots.txt з посиланням на sitemap."""
    sitemap_url = request.build_absolute_uri(reverse('sitemap'))
    body = 'User-agent: *\nAllow: /\n\nSitemap: {}\n'.format(sitemap_url)
    return HttpResponse(body, content_type='text/plain')


def home(request):
    courses = Course.objects.filter(is_published=True)
    return render(request, 'courses/home.html', {'courses': courses, 'user': request.user})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('course_list')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            get_or_create_profile(request)
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect('course_list')
    else:
        form = RegisterForm()
    return render(request, 'registration/register.html', {'form': form})


def course_list(request):
    if not request.user.is_authenticated:
        return redirect(settings.LOGIN_URL + '?next=' + quote(request.path))
    courses = Course.objects.filter(is_published=True)
    return render(request, 'courses/course_list.html', {'courses': courses})


@login_required
def course_detail(request, slug):
    course = Course.objects.filter(slug=slug, is_published=True).first()
    if not course:
        return render(request, '404.html', status=404)
    placement_quiz = course.quizzes.filter(is_published=True, is_placement=True).first()
    # Якщо є вступний тест і користувач ще не проходив його — одразу на тест
    if request.user.is_authenticated and placement_quiz:
        if not QuizAttempt.objects.filter(quiz=placement_quiz, user=request.user).exists():
            return redirect('placement_take', course_slug=course.slug)
    lessons = course.lessons.filter(is_published=True).order_by('order')
    completed_count = count_completed_lessons_for_course(request, course)
    total_lessons = lessons.count()
    completed_lesson_ids = set()
    if request.user.is_authenticated:
        from .models import UserProgress
        completed_lesson_ids = set(
            UserProgress.objects.filter(
                user=request.user, lesson__course=course, completed=True
            ).values_list('lesson_id', flat=True)
        )
    exercises_by_lesson = []
    for lesson in lessons:
        exs = lesson.exercises.filter(is_published=True).order_by('order')
        if exs:
            exercises_by_lesson.append({'lesson': lesson, 'exercises': exs})
    quizzes = course.quizzes.filter(is_published=True).order_by('order')
    avg_rating, rating_count = get_average_rating(course=course)
    return render(request, 'courses/course_detail.html', {
        'course': course,
        'lessons': lessons,
        'completed_count': completed_count,
        'total_lessons': total_lessons,
        'completed_lesson_ids': completed_lesson_ids,
        'exercises_by_lesson': exercises_by_lesson,
        'quizzes': quizzes,
        'placement_quiz': placement_quiz,
        'avg_rating': avg_rating,
        'rating_count': rating_count,
    })


@login_required
def placement_redirect(request, course_slug):
    """Редірект на вступний тест. Якщо вже проходив — одразу на сторінку курсу."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    placement_quiz = course.quizzes.filter(is_published=True, is_placement=True).first()
    if not placement_quiz:
        return redirect('course_detail', slug=course_slug)
    if QuizAttempt.objects.filter(quiz=placement_quiz, user=request.user).exists():
        return redirect('course_detail', slug=course_slug)
    return redirect('quiz_take', quiz_id=placement_quiz.id)


@login_required
def lesson_detail(request, course_slug, lesson_slug):
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    exercises = lesson.exercises.filter(is_published=True).order_by('order')
    all_quizzes = lesson.quizzes.filter(is_published=True).order_by('order')
    quizzes_true_false = [q for q in all_quizzes if q.quiz_type == 'true_false']
    quizzes_single_choice = [q for q in all_quizzes if q.quiz_type == 'single_choice']
    quizzes_match_pairs = [q for q in all_quizzes if q.quiz_type == 'match_pairs']
    lessons_list = list(course.lessons.filter(is_published=True).order_by('order'))
    idx = next((i for i, l in enumerate(lessons_list) if l.pk == lesson.pk), None)
    lessons_prev = lessons_list[idx - 1] if idx and idx > 0 else None
    lessons_next = lessons_list[idx + 1] if idx is not None and idx < len(lessons_list) - 1 else None
    completed_count = count_completed_lessons_for_course(request, course)
    total_lessons = len(lessons_list)
    avg_rating, rating_count = get_average_rating(lesson=lesson)
    return render(request, 'courses/lesson_detail.html', {
        'course': course,
        'lesson': lesson,
        'exercises': exercises,
        'quizzes': all_quizzes,
        'quizzes_true_false': quizzes_true_false,
        'quizzes_single_choice': quizzes_single_choice,
        'quizzes_match_pairs': quizzes_match_pairs,
        'lessons_prev': lessons_prev,
        'lessons_next': lessons_next,
        'completed_count': completed_count,
        'total_lessons': total_lessons,
        'avg_rating': avg_rating,
        'rating_count': rating_count,
    })


@login_required
@require_POST
def lesson_generate_content(request, course_slug, lesson_slug):
    """Генерація конспекту уроку через ШІ та збереження в Lesson.content."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    language = (course.language or 'python').lower()
    content = generate_lesson_content(lesson.title, language)
    if not content:
        return JsonResponse({'ok': False, 'message': 'Не вдалося згенерувати конспект. Перевірте OPENAI_API_KEY.'})
    lesson.content = content
    lesson.save(update_fields=['content'])
    return JsonResponse({'ok': True, 'content': content})


# ——— AI-практика: генерація задачі + перевірка коду (для диплома) ———
@login_required
def lesson_practice(request, course_slug, lesson_slug):
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    topic = lesson.title
    language = course.language.title()
    session_key = f"ai_task_{lesson.id}"
    task = request.session.get(session_key)
    result = None
    code = request.POST.get("code", "").strip() if request.method == "POST" and "check" in request.POST else ""
    ai_available = bool(__import__("os").environ.get("OPENAI_API_KEY"))

    feedback_score = None
    if request.method == "POST":
        if "generate" in request.POST:
            task = ai_generate_task(topic, language)
            if task is None:
                task = "[Помилка: перевірте OPENAI_API_KEY або підключення до інтернету.]"
            request.session[session_key] = task
        elif "check" in request.POST:
            task = request.session.get(session_key) or ""
            code = request.POST.get("code", "").strip()
            if task and not task.startswith("["):
                if code:
                    result = ai_check_code(topic, task, code, language)
                    if result:
                        feedback_score = parse_score_from_feedback(result)
                        AIPracticeAttempt.objects.create(
                            user=request.user,
                            lesson=lesson,
                            task_text=task,
                            code_submitted=code,
                            score=feedback_score,
                            feedback=result,
                        )
                    else:
                        result = "Помилка перевірки. Переконайтесь, що OPENAI_API_KEY задано в середовищі."
                else:
                    result = "Введіть код для перевірки."
            else:
                result = "Спочатку згенеруйте задачу."

    return render(request, "courses/lesson_practice.html", {
        "course": course,
        "lesson": lesson,
        "topic": topic,
        "language": language,
        "task": task,
        "result": result,
        "feedback_score": feedback_score,
        "code": code,
        "ai_available": ai_available,
        "attempts_count": AIPracticeAttempt.objects.filter(user=request.user, lesson=lesson).count(),
    })


@login_required
def lesson_podcast(request, course_slug, lesson_slug):
    """Подкаст: діалог з ШІ — питання по темі уроку, користувач відповідає, ШІ перевіряє і ставить наступне."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    conv = PodcastConversation.objects.filter(user=request.user, lesson=lesson).first()
    messages = (conv.messages or []) if conv else []
    return render(request, 'courses/lesson_podcast.html', {
        'course': course,
        'lesson': lesson,
        'podcast_messages': messages,
    })


@login_required
@require_POST
def lesson_podcast_api(request, course_slug, lesson_slug):
    """API подкасту: приймає повідомлення користувача, повертає відповідь ШІ. Діалог зберігається в БД."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        data = {}
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return JsonResponse({'ok': False, 'reply': 'Напишіть відповідь.'})
    conv, _ = PodcastConversation.objects.get_or_create(
        user=request.user, lesson=lesson,
        defaults={'messages': []},
    )
    history = list(conv.messages or [])[-20:]
    language = (course.language or 'python').lower()
    reply = podcast_reply(
        lesson.title,
        lesson.content,
        history,
        user_message,
        language,
    )
    if not reply:
        return JsonResponse({'ok': False, 'reply': 'Помилка ШІ. Перевірте OPENAI_API_KEY.'})
    history = history + [
        {'role': 'user', 'content': user_message},
        {'role': 'assistant', 'content': reply},
    ]
    conv.messages = history[-50:]
    conv.save(update_fields=['messages', 'updated_at'])
    return JsonResponse({'ok': True, 'reply': reply})


@login_required
def lesson_quiz_ai(request, course_slug, lesson_slug, question_type):
    """Тест з питаннями від ШІ: генерація питань по темі уроку, потім оцінка відповідей."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    if question_type not in ('true_false', 'single_choice', 'match_pairs'):
        return redirect('lesson_detail', course_slug=course_slug, lesson_slug=lesson_slug)
    session_key = f'ai_quiz_{lesson.id}_{question_type}'
    questions = request.session.get(session_key)
    if not questions:
        language = (course.language or 'python').lower()
        num = 5 if question_type != 'match_pairs' else 1
        questions = generate_quiz_questions(
            lesson.title, lesson.content, question_type, num_questions=num, language=language
        )
        if not questions:
            return render(request, 'courses/lesson_quiz_ai.html', {
                'course': course, 'lesson': lesson, 'question_type': question_type,
                'questions': [], 'error': 'Не вдалося згенерувати питання. Перевірте OPENAI_API_KEY.',
            })
        request.session[session_key] = questions
    return render(request, 'courses/lesson_quiz_ai.html', {
        'course': course, 'lesson': lesson, 'question_type': question_type, 'questions': questions,
    })


@login_required
@require_POST
def lesson_quiz_ai_submit(request, course_slug, lesson_slug, question_type):
    """Приймає відповіді на AI-тест, оцінює, повертає JSON."""
    course = get_object_or_404(Course, slug=course_slug, is_published=True)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug, is_published=True)
    if question_type not in ('true_false', 'single_choice', 'match_pairs'):
        return JsonResponse({'ok': False, 'message': 'Невірний тип тесту.'})
    session_key = f'ai_quiz_{lesson.id}_{question_type}'
    questions = request.session.get(session_key)
    if not questions:
        return JsonResponse({'ok': False, 'message': 'Спочатку відкрийте тест (питання згенеруються).'})
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        data = {}
    answers = data.get('answers', [])
    time_spent_minutes = data.get('time_spent_minutes')
    if time_spent_minutes is not None:
        try:
            time_spent_minutes = max(0, int(time_spent_minutes))
        except (TypeError, ValueError):
            time_spent_minutes = None
    language = (course.language or 'python').lower()
    result = evaluate_quiz_answers(lesson.title, questions, answers, question_type, language)
    if not result:
        return JsonResponse({'ok': False, 'message': 'Помилка оцінки.'})
    request.session.pop(session_key, None)
    correct_count = result['correct_count']
    # 1 правильна відповідь = 1 бал
    profile = get_or_create_profile(request)
    add_points(profile, correct_count)
    from .models import AILessonQuizAttempt
    from .services import check_and_award_achievements
    AILessonQuizAttempt.objects.get_or_create(
        user=request.user,
        lesson=lesson,
        question_type=question_type,
        defaults={}
    )
    new_achievements = check_and_award_achievements(request, profile)
    payload = {
        'ok': True,
        'correct_count': correct_count,
        'total': result['total'],
        'feedback': result['feedback'],
        'score': result.get('score'),
        'points_added': correct_count,
        'new_achievements': new_achievements,
    }
    if time_spent_minutes is not None:
        payload['time_spent_minutes'] = time_spent_minutes
    return JsonResponse(payload)


def exercise_run(request):
    return JsonResponse({'ok': True, 'message': 'Код виконано (демо)'})


# ——— Очівки (досягнення, як у ZNO Hub: розблоковані / заблоковані) ———
@login_required
def achievements_list(request):
    from .services import check_and_award_achievements
    profile = get_or_create_profile(request)
    check_and_award_achievements(request, profile)
    earned_ids = set(
        UserAchievement.objects.filter(user=request.user).values_list('achievement_id', flat=True)
    )
    all_ordered = list(Achievement.objects.all().order_by('order', 'name'))
    # спочатку відкриті (отримані), потім заблоковані
    all_achievements = [a for a in all_ordered if a.id in earned_ids] + [a for a in all_ordered if a.id not in earned_ids]
    return render(request, 'courses/achievements_list.html', {
        'all_achievements': all_achievements,
        'earned_ids': earned_ids,
        'quizzes_passed': count_quizzes_passed(request),
        'completed_lessons': count_completed_lessons(request),
        'profile': profile,
    })


# ——— Редагування профілю (фото, ім'я, email) ———
@login_required
def profile_edit(request):
    profile = get_or_create_profile(request)
    form = ProfileEditForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        profile=profile,
    )
    if form.is_valid():
        form.save()
        return redirect('dashboard')
    return render(request, 'courses/profile_edit.html', {'form': form, 'profile': profile})


# ——— Dashboard (гейміфікація + статистика) ———
@login_required
def dashboard(request):
    profile = get_or_create_profile(request)
    q = Q()
    if profile.session_key:
        q |= Q(session_key=profile.session_key)
    if profile.user_id:
        q |= Q(user=profile.user)
    earned = UserAchievement.objects.filter(q).select_related('achievement').order_by('-earned_at')[:20]
    leagues = League.objects.all().order_by('min_points')
    weekly_study = get_weekly_study_time(request)
    quizzes_passed = count_quizzes_passed(request)
    return render(request, 'courses/dashboard.html', {
        'profile': profile,
        'earned_achievements': earned,
        'leagues': leagues,
        'completed_lessons': count_completed_lessons(request),
        'weekly_study': weekly_study,
        'quizzes_passed': quizzes_passed,
    })


# ——— Рейтинги ———
@require_POST
def rate(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        data = {}
    target = data.get('target')
    course_id = data.get('course_id')
    lesson_id = data.get('lesson_id')
    try:
        score = max(1, min(5, int(data.get('score', 5))))
    except (TypeError, ValueError):
        score = 5
    comment = (data.get('comment') or '').strip()[:500]
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    if target == 'course' and course_id is not None:
        try:
            course = get_object_or_404(Course, pk=int(course_id), is_published=True)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False}, status=400)
        kw = {'course': course, 'lesson': None}
        kw['user'] = request.user if request.user.is_authenticated else None
        kw['session_key'] = None if request.user.is_authenticated else session_key
        r = Rating.objects.filter(**kw).first()
        if r:
            r.score = score
            r.comment = comment
            r.save()
        else:
            Rating.objects.create(**kw, score=score, comment=comment)
        avg, count = get_average_rating(course=course)
        return JsonResponse({'ok': True, 'avg': avg, 'count': count})
    if target == 'lesson' and lesson_id is not None:
        try:
            lesson = get_object_or_404(Lesson, pk=int(lesson_id))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False}, status=400)
        kw = {'course': None, 'lesson': lesson}
        kw['user'] = request.user if request.user.is_authenticated else None
        kw['session_key'] = None if request.user.is_authenticated else session_key
        r = Rating.objects.filter(**kw).first()
        if r:
            r.score = score
            r.comment = comment
            r.save()
        else:
            Rating.objects.create(**kw, score=score, comment=comment)
        avg, count = get_average_rating(lesson=lesson)
        return JsonResponse({'ok': True, 'avg': avg, 'count': count})
    return JsonResponse({'ok': False}, status=400)


# ——— Завершити урок (бали + вогник) ———
@login_required
@require_POST
def lesson_complete(request, course_slug, lesson_slug):
    lesson = get_object_or_404(Lesson, course__slug=course_slug, slug=lesson_slug)
    new_achievements = award_lesson_complete(request, lesson)
    return JsonResponse({
        'ok': True,
        'points': 15,
        'new_achievements': new_achievements or [],
    })


# ——— Лідерборд ———
@login_required
def leaderboard(request):
    top = get_leaderboard(50)
    return render(request, 'courses/leaderboard.html', {'leaderboard': top})


# ——— Ліги (Мапа) ———
@login_required
def leagues_map(request):
    top = get_leaderboard(10)
    from .models import League
    leagues = League.objects.all().order_by('order')
    profile = get_or_create_profile(request)
    
    current_league_name = profile.league.name if profile.league else "Осіння ліга"
    current_league_icon = profile.league.icon if profile.league else "🔘"
    
    # 5 етапів для поточної ліги. Можна брати з БД, тут - динамічний розрахунок
    completed_sectors = min(5, profile.points // 50)
    
    user_leagues = GroupLeagueMember.objects.filter(user=request.user).select_related('league')
    public_leagues = GroupLeague.objects.filter(is_public=True).exclude(members__user=request.user)
    
    context = {
        'leaderboard': top,
        'leagues': leagues,
        'profile': profile,
        'current_league_name': current_league_name,
        'current_league_icon': current_league_icon,
        'completed_sectors': completed_sectors,
        'user_leagues': user_leagues,
        'public_leagues': public_leagues,
    }
    return render(request, 'courses/leagues_map.html', context)


# ——— Змагання ———
@login_required
def competition_list(request):
    now = timezone.now()
    competitions = Competition.objects.filter(is_active=True).order_by('-start_at')
    return render(request, 'courses/competition_list.html', {'competitions': competitions, 'now': now})


@login_required
def competition_detail(request, slug):
    comp = get_object_or_404(Competition, slug=slug)
    top = get_leaderboard(30)  # у межах змагання можна фільтрувати по даті; для простоти — глобальний топ
    return render(request, 'courses/competition_detail.html', {'competition': comp, 'leaderboard': top})


# ——— Тести ———
@login_required
def quiz_list(request, course_slug=None):
    if course_slug:
        course = get_object_or_404(Course, slug=course_slug, is_published=True)
        quizzes = course.quizzes.filter(is_published=True).order_by('order')
        return render(request, 'courses/quiz_list.html', {'course': course, 'quizzes': quizzes})
    quizzes = Quiz.objects.filter(is_published=True).order_by('course__order', 'order')
    return render(request, 'courses/quiz_list.html', {'quizzes': quizzes, 'course': None})


@login_required
def quiz_take(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, is_published=True)
    # Вступний тест проходять лише один раз — якщо вже є спроба, на сторінку курсу
    if getattr(quiz, 'is_placement', False) and quiz.course_id:
        if QuizAttempt.objects.filter(quiz=quiz, user=request.user).exists():
            return redirect('course_detail', slug=quiz.course.slug)
    questions = list(quiz.questions.order_by('order'))
    for q in questions:
        q_type = q.question_type or quiz.quiz_type
        q_data = getattr(q, 'data', None) or {}
        q.items_json = json.dumps(q_data.get('items', [])) if q_type == 'ordering' else '[]'
        q.match_pairs = q_data.get('pairs', [])
        q.options = q_data.get('options', [])
        q.items_list = q_data.get('items', [])
        q.blanks_list = q_data.get('blanks', [])
    context = {'quiz': quiz, 'questions': questions}
    if getattr(quiz, 'is_placement', False) and quiz.course_id:
        context['course'] = quiz.course
        session_key = 'placement_task_%s' % quiz_id
        if session_key not in request.session:
            task = generate_placement_task(quiz.course.language)
            if task:
                request.session[session_key] = task
        context['placement_task'] = request.session.get(session_key)
    return render(request, 'courses/quiz_take.html', context)


@login_required
@require_POST
def quiz_submit(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, is_published=True)
    # Вступний тест приймається лише один раз
    if getattr(quiz, 'is_placement', False) and quiz.course_id:
        if QuizAttempt.objects.filter(quiz=quiz, user=request.user).exists():
            return JsonResponse({
                'ok': False,
                'already_passed': True,
                'message': 'Ви вже проходили вступний тест.',
                'redirect_url': reverse('course_detail', kwargs={'slug': quiz.course.slug}),
            })
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        data = {}
    answers = data.get('answers', [])
    placement_task_answer = data.get('placement_task_answer', '')
    time_spent_minutes = data.get('time_spent_minutes')
    if time_spent_minutes is not None:
        try:
            time_spent_minutes = max(0, int(time_spent_minutes))
        except (TypeError, ValueError):
            time_spent_minutes = None
    questions = list(quiz.questions.order_by('order'))
    total_questions = len(questions)
    correct_count = 0
    for q in questions:
        ans = next((a for a in answers if a.get('question_id') == q.id), None)
        if not ans:
            continue
        user_answer = ans.get('answer')
        q_type = q.question_type or quiz.quiz_type
        if q_type == 'single_choice':
            opts = q.data.get('options', [])
            correct = next((o for o in opts if o.get('correct')), None)
            if correct and str(user_answer) == str(correct.get('text', '')):
                correct_count += 1
        elif q_type == 'multiple_choice':
            opts = q.data.get('options', [])
            correct_texts = set(str(o.get('text')) for o in opts if o.get('correct'))
            user_set = set(user_answer) if isinstance(user_answer, list) else {str(user_answer)}
            if correct_texts and user_set == correct_texts:
                correct_count += 1
        elif q_type == 'true_false':
            correct = q.data.get('correct', True)
            if str(user_answer).lower() in ('true', 'false', 'так', 'ні', '1', '0'):
                u = str(user_answer).lower()
                if (u in ('true', 'так', '1') and correct) or (u in ('false', 'ні', '0') and not correct):
                    correct_count += 1
        elif q_type == 'flashcard':
            back = (q.data.get('back') or '').strip().lower()
            if str(user_answer).strip().lower() == back:
                correct_count += 1
        elif q_type == 'ordering':
            items = q.data.get('items', [])
            if isinstance(user_answer, list) and len(user_answer) == len(items):
                if user_answer == items:
                    correct_count += 1
        elif q_type == 'fill_blank':
            blanks = q.data.get('blanks', [])
            if isinstance(user_answer, list) and len(user_answer) >= len(blanks):
                if all(
                    str(user_answer[i]).strip().lower() == str(blanks[i]).strip().lower()
                    for i in range(len(blanks))
                ):
                    correct_count += 1
        elif q_type == 'match_pairs':
            pairs = q.data.get('pairs', [])
            if isinstance(user_answer, list):
                correct_pairs = set(tuple(p) if isinstance(p, list) else (p.get('left'), p.get('right')) for p in pairs)
                user_pairs = set(tuple(x) if isinstance(x, (list, tuple)) else (x.get('left'), x.get('right')) for x in user_answer)
                if correct_pairs == user_pairs:
                    correct_count += 1
    points_earned = correct_count
    placement_bonus = 0
    QuizAttempt.objects.create(
        quiz=quiz,
        user=request.user,
        score=correct_count,
        max_score=total_questions,
        is_practice=quiz.is_practice,
    )
    new_achievements = award_quiz_complete(request, quiz, points_earned, total_questions, quiz.is_practice)
    if getattr(quiz, 'is_placement', False):
        profile = get_or_create_profile(request)
        placement_bonus = 20
        add_points(profile, placement_bonus)
    percent = round(100 * correct_count / total_questions, 0) if total_questions else 0
    total_points_added = (0 if quiz.is_practice else points_earned) + placement_bonus
    payload = {
        'ok': True,
        'correct': correct_count,
        'total': total_questions,
        'percent': percent,
        'points_added': total_points_added,
        'placement_bonus': placement_bonus,
        'new_achievements': new_achievements or [],
    }
    if time_spent_minutes is not None:
        payload['time_spent_minutes'] = time_spent_minutes
    # Вступний тест: визначити рівень, з якого уроку починати, вивести результат
    if getattr(quiz, 'is_placement', False) and quiz.course_id:
        lessons_ordered = list(
            quiz.course.lessons.filter(is_published=True).order_by('order')
        )
        if lessons_ordered:
            if percent >= 70 and len(lessons_ordered) >= 20:
                target_lesson = lessons_ordered[19]
                level_label = 'високий'
            elif percent >= 70 and len(lessons_ordered) > 10:
                target_lesson = lessons_ordered[-1]
                level_label = 'високий'
            elif len(lessons_ordered) >= 10:
                target_lesson = lessons_ordered[9]
                level_label = 'середній'
            else:
                target_lesson = lessons_ordered[0]
                level_label = 'початковий'
            payload['redirect_url'] = reverse(
                'lesson_detail',
                kwargs={
                    'course_slug': quiz.course.slug,
                    'lesson_slug': target_lesson.slug,
                },
            )
            lesson_num = lessons_ordered.index(target_lesson) + 1
            payload['placement_result'] = {
                'level': level_label,
                'lesson_title': target_lesson.title,
                'lesson_num': lesson_num,
                'start_lesson_text': 'Ви можете починати вивчення матеріалу з уроку %s — «%s».' % (lesson_num, target_lesson.title),
            }
        else:
            payload['redirect_url'] = reverse('course_detail', kwargs={'slug': quiz.course.slug})
        # Оцінка завдання від ШІ та коефіцієнт
        session_key = 'placement_task_%s' % quiz_id
        placement_task = request.session.get(session_key)
        ai_score_normalized = 0.5
        payload['placement_ai_feedback'] = ''
        payload['placement_ai_solution'] = ''
        if isinstance(placement_task, dict) and placement_task.get('full_task'):
            eval_result = evaluate_placement_answer(
                placement_task['full_task'],
                placement_task_answer,
                quiz.course.language,
            )
            if eval_result:
                payload['placement_ai_feedback'] = eval_result.get('feedback', '')
                payload['placement_ai_solution'] = eval_result.get('solution', '')
                ai_score_normalized = eval_result.get('score', 5) / 10.0
        quiz_part = (correct_count / total_questions) if total_questions else 0
        payload['placement_coefficient'] = round(0.7 * quiz_part + 0.3 * ai_score_normalized, 3)
    return JsonResponse(payload)


# ——— Кастомні Ліги (Групи) ———
@login_required
def group_league_list(request):
    user_leagues = GroupLeagueMember.objects.filter(user=request.user).select_related('league')
    public_leagues = GroupLeague.objects.filter(is_public=True).exclude(members__user=request.user)
    return render(request, 'courses/leagues/league_list.html', {
        'user_leagues': user_leagues,
        'public_leagues': public_leagues,
    })

@login_required
def group_league_create(request):
    if request.method == 'POST':
        form = GroupLeagueForm(request.POST, request.FILES)
        if form.is_valid():
            league = form.save(commit=False)
            league.created_by = request.user
            league.save()
            GroupLeagueMember.objects.create(league=league, user=request.user, role='admin')
            
            target_tasks = form.cleaned_data.get('target_tasks', 20)
            LeagueChallenge.objects.create(
                league=league,
                title="Головна ціль ліги",
                description=f"Вирішити {target_tasks} завдань для проходження цієї ліги.",
                goal_type='tasks',
                target_value=target_tasks,
                start_date=timezone.now(),
                end_date=timezone.now() + timezone.timedelta(days=30)
            )
            return redirect('group_league_detail', pk=league.pk)
    else:
        form = GroupLeagueForm()
    return render(request, 'courses/leagues/league_form.html', {'form': form})

@login_required
def group_league_detail(request, pk):
    league = get_object_or_404(GroupLeague, pk=pk)
    member = GroupLeagueMember.objects.filter(league=league, user=request.user).first()
    if not member and not league.is_public:
        return redirect('group_league_list')
        
    members = league.members.select_related('user__game_profile').order_by('-points', 'joined_at')
    challenges = league.challenges.all().order_by('target_value')
    messages = league.messages.select_related('user__game_profile').order_by('-created_at')[:50]
    
    challenge_form = LeagueChallengeForm() if member and member.role == 'admin' else None
    message_form = LeagueMessageForm() if member else None

    return render(request, 'courses/leagues/league_detail.html', {
        'league': league,
        'member': member,
        'members': members,
        'challenges': challenges,
        'messages': reversed(messages),
        'challenge_form': challenge_form,
        'message_form': message_form,
    })

@login_required
def group_league_join(request):
    if request.method == 'POST':
        code = request.POST.get('join_code', '').strip().upper()
        if code:
            league = GroupLeague.objects.filter(join_code=code).first()
            if league:
                if not GroupLeagueMember.objects.filter(league=league, user=request.user).exists():
                    GroupLeagueMember.objects.create(league=league, user=request.user)
                return redirect('group_league_detail', pk=league.pk)
    return redirect('group_league_list')

@login_required
@require_POST
def group_league_leave(request, pk):
    league = get_object_or_404(GroupLeague, pk=pk)
    GroupLeagueMember.objects.filter(league=league, user=request.user).delete()
    return redirect('group_league_list')

@login_required
@require_POST
def group_league_remove(request, pk, user_id):
    league = get_object_or_404(GroupLeague, pk=pk)
    admin_member = GroupLeagueMember.objects.filter(league=league, user=request.user, role='admin').first()
    if admin_member:
        GroupLeagueMember.objects.filter(league=league, user_id=user_id).exclude(user=request.user).delete()
    return redirect('group_league_detail', pk=pk)

@login_required
@require_POST
def group_league_delete(request, pk):
    league = get_object_or_404(GroupLeague, pk=pk)
    if league.created_by == request.user:
        league.delete()
    return redirect('group_league_list')

@login_required
@require_POST
def group_league_chat(request, pk):
    league = get_object_or_404(GroupLeague, pk=pk)
    if GroupLeagueMember.objects.filter(league=league, user=request.user).exists():
        form = LeagueMessageForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.league = league
            msg.user = request.user
            msg.save()
    return redirect('group_league_detail', pk=pk)

@login_required
@require_POST
def group_league_challenge_create(request, pk):
    league = get_object_or_404(GroupLeague, pk=pk)
    member = GroupLeagueMember.objects.filter(league=league, user=request.user, role='admin').first()
    if member:
        form = LeagueChallengeForm(request.POST)
        if form.is_valid():
            challenge = form.save(commit=False)
            challenge.league = league
            challenge.start_date = timezone.now()
            challenge.save()
    return redirect('group_league_detail', pk=pk)
