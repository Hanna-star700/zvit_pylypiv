from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


# ——— Рейтинги ———
class Rating(models.Model):
    course = models.ForeignKey(
        'Course', on_delete=models.CASCADE, null=True, blank=True, related_name='ratings'
    )
    lesson = models.ForeignKey(
        'Lesson', on_delete=models.CASCADE, null=True, blank=True, related_name='ratings'
    )
    session_key = models.CharField('Сесія', max_length=40, null=True, blank=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='ratings'
    )
    score = models.PositiveSmallIntegerField('Оцінка (1–5)', default=5)
    comment = models.TextField('Коментар', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Рейтинг'
        verbose_name_plural = 'Рейтинги'

    def __str__(self):
        target = self.course or self.lesson
        return f'{target}: {self.score}★'


# ——— Ліги (гейміфікація) ———
class League(models.Model):
    name = models.CharField('Назва', max_length=100)
    slug = models.SlugField(unique=True)
    min_points = models.PositiveIntegerField('Мін. балів', default=0)
    icon = models.CharField('Іконка', max_length=20, default='🥉')
    color = models.CharField('Колір', max_length=7, default='#cd7f32')
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        ordering = ['order', 'min_points']
        verbose_name = 'Ліга'
        verbose_name_plural = 'Ліги'

    def __str__(self):
        return self.name


# ——— Профіль гравця (бали, вогник, ліга, аватар) ———
def avatar_upload_to(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    uid = instance.user_id or (instance.session_key or 'anon')[:8]
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'avatars/{uid}_{ts}.{ext}'


class GameProfile(models.Model):
    session_key = models.CharField('Сесія', max_length=40, unique=True, null=True, blank=True)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='game_profile'
    )
    avatar = models.ImageField('Фото', upload_to=avatar_upload_to, null=True, blank=True)
    points = models.PositiveIntegerField('Бали', default=0)
    streak_days = models.PositiveIntegerField('Вогник (дні поспіль)', default=0)
    last_activity_date = models.DateField('Остання активність', null=True, blank=True)
    league = models.ForeignKey(
        League, on_delete=models.SET_NULL, null=True, blank=True, related_name='profiles'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ігровий профіль'
        verbose_name_plural = 'Ігрові профілі'

    def __str__(self):
        return f'{self.session_key or self.user}: {self.points} pts'

    @property
    def rank_title(self):
        if self.points >= 5000:
            return 'Senior'
        elif self.points >= 1000:
            return 'Middle'
        else:
            return 'Junior'



# ——— Досягнення ———
class Achievement(models.Model):
    name = models.CharField('Назва', max_length=150)
    slug = models.SlugField(unique=True)
    description = models.TextField('Опис', blank=True)
    icon = models.CharField('Іконка', max_length=20, default='🏆')
    points_reward = models.PositiveIntegerField('Бонус балів', default=0)
    condition_type = models.CharField(
        'Умова',
        max_length=50,
        choices=[
            ('first_lesson', 'Перший завершений урок'),
            ('lessons_5', '5 уроків'),
            ('lessons_10', '10 уроків'),
            ('lessons_15', '15 уроків'),
            ('quiz_perfect', 'Ідеальний тест'),
            ('first_quiz', 'Перший пройдений тест'),
            ('quizzes_5', '5 пройдених тестів'),
            ('quizzes_10', '10 пройдених тестів'),
            ('quizzes_50', '50 пройдених тестів'),
            ('quizzes_100', '100 пройдених тестів'),
            ('streak_3', 'Вогник 3 дні'),
            ('streak_7', 'Вогник 7 днів'),
            ('streak_14', 'Вогник 14 днів'),
            ('points_100', '100 балів'),
            ('points_500', '500 балів'),
            ('points_1000', '1000 балів'),
            ('first_league', 'Вступ до ліги'),
            ('league_top', 'Топ місця в лізі'),
            ('challenge_done', 'Виконано челендж'),
        ],
        default='first_lesson',
    )
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Досягнення'
        verbose_name_plural = 'Досягнення'

    def __str__(self):
        return self.name


class UserAchievement(models.Model):
    session_key = models.CharField(max_length=40, null=True, blank=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='earned_achievements'
    )
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='earned_by')
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Отримане досягнення'
        verbose_name_plural = 'Отримані досягнення'


# ——— Змагання ———
class Competition(models.Model):
    name = models.CharField('Назва', max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField('Опис', blank=True)
    start_at = models.DateTimeField('Початок')
    end_at = models.DateTimeField('Кінець')
    is_active = models.BooleanField('Активне', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Змагання'
        verbose_name_plural = 'Змагання'

    def __str__(self):
        return self.name


# ——— Тести / квізи ———
class Quiz(models.Model):
    QUIZ_TYPES = [
        ('single_choice', 'Один правильний варіант'),
        ('multiple_choice', 'Кілька правильних'),
        ('true_false', 'Так / Ні'),
        ('flashcard', 'Картки (питання–відповідь)'),
        ('match_pairs', 'З\'єднати пари'),
        ('ordering', 'Впорядкування'),
        ('fill_blank', 'Пропущене слово / код'),
    ]
    lesson = models.ForeignKey(
        'Lesson', on_delete=models.CASCADE, null=True, blank=True, related_name='quizzes'
    )
    course = models.ForeignKey(
        'Course', on_delete=models.CASCADE, null=True, blank=True, related_name='quizzes'
    )
    title = models.CharField('Назва', max_length=200)
    quiz_type = models.CharField('Тип', max_length=20, choices=QUIZ_TYPES)
    is_practice = models.BooleanField('Тренувальний режим (без оцінки)', default=False)
    is_placement = models.BooleanField('Вступний тест (визначення рівня)', default=False)
    points_per_question = models.PositiveIntegerField('Балів за питання', default=10)
    order = models.PositiveIntegerField('Порядок', default=0)
    is_published = models.BooleanField('Опубліковано', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'title']
        verbose_name = 'Тест'
        verbose_name_plural = 'Тести'

    def __str__(self):
        return self.title

    def question_count(self):
        return self.questions.count()


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField('Текст питання / передня сторона картки')
    question_type = models.CharField(
        'Тип',
        max_length=20,
        choices=Quiz.QUIZ_TYPES,
        blank=True,
    )  # порожнє = тип квізу
    order = models.PositiveIntegerField('Порядок', default=0)
    # Гнучкі дані: options, correct, back (flashcard), pairs, items (ordering), blanks
    data = models.JSONField('Дані (варіанти, пари, тощо)', default=dict, blank=True)

    class Meta:
        ordering = ['quiz', 'order']
        verbose_name = 'Питання'
        verbose_name_plural = 'Питання'

    def __str__(self):
        return self.text[:50] + '…' if len(self.text) > 50 else self.text


class QuizAttempt(models.Model):
    session_key = models.CharField(max_length=40, null=True, blank=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='quiz_attempts'
    )
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    score = models.PositiveIntegerField('Бали', default=0)
    max_score = models.PositiveIntegerField('Макс. балів', default=0)
    is_practice = models.BooleanField('Тренувальний режим', default=False)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Спроба тесту'
        verbose_name_plural = 'Спроби тестів'


class Course(models.Model):
    LANG_CHOICES = [
        ('python', 'Python'),
        ('javascript', 'JavaScript'),
    ]
    title = models.CharField('Назва', max_length=200)
    slug = models.SlugField(unique=True)
    language = models.CharField('Мова', max_length=20, choices=LANG_CHOICES)
    short_description = models.CharField('Короткий опис', max_length=300)
    description = models.TextField('Опис')
    duration_hours = models.PositiveIntegerField('Тривалість (год)', default=24)
    level = models.CharField('Рівень', max_length=50, default='Початковий')
    order = models.PositiveIntegerField('Порядок', default=0)
    icon = models.CharField('Іконка/емодзі', max_length=10, default='🐍')
    color = models.CharField('Колір (hex)', max_length=7, default='#3776ab')  # Python blue / JS yellow
    is_published = models.BooleanField('Опубліковано', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'title']
        verbose_name = 'Курс'
        verbose_name_plural = 'Курси'

    def __str__(self):
        return self.title

    def lesson_count(self):
        return self.lessons.count()

    def exercise_count(self):
        return Exercise.objects.filter(lesson__course=self).count()


class Lesson(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField('Назва', max_length=200)
    slug = models.SlugField()
    content = models.TextField('Контент (HTML/Markdown)')
    order = models.PositiveIntegerField('Порядок', default=0)
    duration_minutes = models.PositiveIntegerField('Хвилин', default=15)
    is_published = models.BooleanField('Опубліковано', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['course', 'order']
        unique_together = [['course', 'slug']]
        verbose_name = 'Урок'
        verbose_name_plural = 'Уроки'

    def __str__(self):
        return f"{self.course.title}: {self.title}"


class Exercise(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='exercises')
    title = models.CharField('Назва', max_length=200)
    instruction = models.TextField('Інструкція')
    starter_code = models.TextField('Початковий код', blank=True)
    solution = models.TextField('Рішення (для перевірки)', blank=True)
    hint = models.TextField('Підказка', blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)
    is_published = models.BooleanField('Опубліковано', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['lesson', 'order']
        verbose_name = 'Завдання'
        verbose_name_plural = 'Завдання'

    def __str__(self):
        return self.title


class UserProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_progress', null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)  # for anonymous
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='progress')
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Прогрес'
        verbose_name_plural = 'Прогрес'

    def __str__(self):
        return f"{self.lesson.title} - {'Done' if self.completed else 'In progress'}"


# ——— Час навчання по днях (як у Duolingo) ———
class DailyStudyTime(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_study_times')
    date = models.DateField('Дата')
    minutes = models.PositiveIntegerField('Хвилин', default=0)

    class Meta:
        unique_together = [['user', 'date']]
        ordering = ['-date']
        verbose_name = 'Час навчання за день'
        verbose_name_plural = 'Час навчання за день'

    def __str__(self):
        return f"{self.user.username} — {self.date}: {self.minutes} хв"


# ——— AI-практика: згенерована задача + перевірка коду (для диплома) ———
class AIPracticeAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_practice_attempts')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='ai_practice_attempts')
    task_text = models.TextField('Текст задачі')
    code_submitted = models.TextField('Код студента', blank=True)
    score = models.PositiveSmallIntegerField('Оцінка (1–10)', null=True, blank=True)
    feedback = models.TextField('Відгук AI', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Спроба AI-практики'
        verbose_name_plural = 'Спроби AI-практики'

    def __str__(self):
        return f"{self.lesson.title} — {self.user.username} — {self.score or '?'}/10"


# ——— Подкаст: збереження діалогу з ШІ по темі уроку ———
class PodcastConversation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='podcast_conversations')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='podcast_conversations')
    messages = models.JSONField('Повідомлення', default=list)  # [{"role": "user"|"assistant", "content": "..."}, ...]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'lesson']]
        ordering = ['-updated_at']
        verbose_name = 'Діалог подкасту'
        verbose_name_plural = 'Діалоги подкастів'

    def __str__(self):
        return f"{self.lesson.title} — {self.user.username}"


# ——— AI-тести до уроку: запис про пройдений тест (для підрахунку досягнень) ———
class AILessonQuizAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_lesson_quiz_attempts')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='ai_lesson_quiz_attempts')
    question_type = models.CharField('Тип тесту', max_length=30)  # true_false, single_choice, match_pairs
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        verbose_name = 'Пройдений AI-тест уроку'
        verbose_name_plural = 'Пройдені AI-тести уроків'

    def __str__(self):
        return f"{self.lesson.title} ({self.question_type}) — {self.user.username}"



# ——— Кастомні Ліги (Групи) ———
class GroupLeague(models.Model):
    name = models.CharField('Назва', max_length=150)
    description = models.TextField('Опис', blank=True)
    is_public = models.BooleanField('Публічна', default=True)
    join_code = models.CharField('Код приєднання', max_length=10, unique=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_group_leagues')
    created_at = models.DateTimeField(auto_now_add=True)
    avatar = models.ImageField('Аватар ліги', upload_to='league_avatars/', null=True, blank=True)
    
    class Meta:
        verbose_name = 'Кастомна Ліга'
        verbose_name_plural = 'Кастомні Ліги'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.join_code:
            self.join_code = str(uuid.uuid4())[:8].upper()
        super().save(*args, **kwargs)

class GroupLeagueMember(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Адміністратор'),
        ('member', 'Учасник'),
    ]
    league = models.ForeignKey(GroupLeague, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_leagues')
    role = models.CharField('Роль', max_length=10, choices=ROLE_CHOICES, default='member')
    points = models.PositiveIntegerField('Бали в поточному сезоні', default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['league', 'user']]
        verbose_name = 'Учасник ліги'
        verbose_name_plural = 'Учасники ліги'
        ordering = ['-points', 'joined_at']

    def __str__(self):
        return f"{self.user.username} - {self.league.name} ({self.points} pts)"

class LeagueChallenge(models.Model):
    GOAL_CHOICES = [
        ('points', 'Набрати бали'),
        ('tasks', 'Вирішити завдання'),
    ]
    league = models.ForeignKey(GroupLeague, on_delete=models.CASCADE, related_name='challenges')
    title = models.CharField('Назва челенджу', max_length=200)
    description = models.TextField('Опис', blank=True)
    goal_type = models.CharField('Тип цілі', max_length=20, choices=GOAL_CHOICES, default='tasks')
    target_value = models.PositiveIntegerField('Цільове значення')
    start_date = models.DateTimeField('Початок')
    end_date = models.DateTimeField('Кінець')
    is_active = models.BooleanField('Активний', default=True)

    class Meta:
        verbose_name = 'Челендж ліги'
        verbose_name_plural = 'Челенджі ліги'
        ordering = ['-end_date']

    def __str__(self):
        return f"{self.league.name}: {self.title}"

class LeagueSeasonResult(models.Model):
    league = models.ForeignKey(GroupLeague, on_delete=models.CASCADE, related_name='season_results')
    season_name = models.CharField('Назва сезону', max_length=100)
    end_date = models.DateTimeField('Дата завершення', auto_now_add=True)
    winners_data = models.JSONField('Результати', default=dict) # Store top 3 users and points

    class Meta:
        verbose_name = 'Результат сезону'
        verbose_name_plural = 'Результати сезонів'
        ordering = ['-end_date']

class LeagueMessage(models.Model):
    league = models.ForeignKey(GroupLeague, on_delete=models.CASCADE, related_name='messages')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='league_messages')
    text = models.TextField('Повідомлення')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Повідомлення ліги'
        verbose_name_plural = 'Повідомлення ліг'
        ordering = ['created_at']


# ——— Щоденні Квести ———
class DailyQuest(models.Model):
    QUEST_TYPES = [
        ('lesson', 'Завершити урок'),
        ('points', 'Набрати бали'),
        ('quiz', 'Пройти тест'),
    ]
    name = models.CharField('Назва квесту', max_length=200)
    quest_type = models.CharField('Тип', max_length=20, choices=QUEST_TYPES)
    target_value = models.PositiveIntegerField('Цільове значення')
    xp_reward = models.PositiveIntegerField('Нагорода (XP)', default=50)
    icon = models.CharField('Іконка', max_length=10, default='📜')

    class Meta:
        verbose_name = 'Щоденний квест'
        verbose_name_plural = 'Щоденні квести'

    def __str__(self):
        return self.name

class UserQuestProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quest_progress')
    quest = models.ForeignKey(DailyQuest, on_delete=models.CASCADE)
    current_value = models.PositiveIntegerField('Поточне значення', default=0)
    is_completed = models.BooleanField('Виконано', default=False)
    date = models.DateField('Дата', auto_now_add=True)

    class Meta:
        unique_together = [['user', 'quest', 'date']]
        verbose_name = 'Прогрес квесту'
        verbose_name_plural = 'Прогрес квестів'

    def __str__(self):
        return f"{self.user.username} - {self.quest.name} ({self.current_value}/{self.quest.target_value})"
