from django import forms
from django.db.models import Q
from accounts.models import User
from projects.models import TicketStatus, TicketType
from projects.forms import UserChoice, AdminChoices
from projects.services import visible_projects
from .models import Ticket


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        values = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(value, initial) for value in values]


class MasterChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name + ('（無効・現在値の保持のみ）' if not obj.is_active else '')


class TicketForm(forms.Form):
    title = forms.CharField(label='タイトル', max_length=200)
    description_markdown = forms.CharField(label='説明（Markdown）', required=False, max_length=100000, strip=False, widget=forms.Textarea(attrs={'rows':6}))
    status_id = MasterChoice(label='ステータス', queryset=TicketStatus.objects.none())
    type_id = MasterChoice(label='種別', queryset=TicketType.objects.none())
    priority = forms.ChoiceField(label='優先度', choices=Ticket.PRIORITIES, initial='medium')
    assignee_id = UserChoice(label='担当者', required=False, queryset=User.objects.none(), empty_label='未割り当て')
    start_date = forms.DateField(label='開始日', required=False, widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'))
    due_date = forms.DateField(label='期限', required=False, widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'))

    def __init__(self, *args, project, ticket=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field, model in [('status_id', TicketStatus), ('type_id', TicketType)]:
            self.fields[field].queryset = model.objects.filter(project=project).filter(Q(is_active=True) | Q(pk=getattr(ticket, field, None)))
        self.fields['assignee_id'].queryset = User.objects.filter(is_active=True, is_special=False, membership__project=project).order_by('username')
        if not ticket:
            self.initial.update(status_id=TicketStatus.objects.filter(project=project, builtin_code='open').values_list('id', flat=True).first(),
                type_id=TicketType.objects.filter(project=project, name='タスク', is_active=True).values_list('id', flat=True).first())

    def service_data(self):
        return {k: (v.pk if v else None) if k in ('status_id','type_id','assignee_id') else v for k,v in self.cleaned_data.items()}


class CommentForm(forms.Form):
    body_markdown = forms.CharField(label='コメント', max_length=100000, required=False, strip=False,
                                    widget=forms.Textarea(attrs={'rows':3}))
    attachments = MultipleFileField(label='ファイル添付', required=False)

    def clean_attachments(self):
        files = self.cleaned_data['attachments']
        if len(files) > 10:
            raise forms.ValidationError('1コメントに添付できるファイルは10個までです。')
        for file in files:
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('ファイルは1個あたり10 MiB以下にしてください。')
        return files

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('body_markdown', '').strip() and not cleaned.get('attachments'):
            raise forms.ValidationError('コメント本文または添付ファイルを指定してください。')
        return cleaned


class NamedChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        if hasattr(obj, 'project'):
            return f'{obj.project.name} / {obj.name}' + ('（無効）' if not obj.is_active else '')
        return obj.name


class SearchDropdown(forms.CheckboxSelectMultiple):
    template_name = 'widgets/search_dropdown.html'


class SearchForm(forms.Form):
    project_id = NamedChoices(label='プロジェクト', queryset=None, required=False)
    status_id = NamedChoices(label='ステータス', queryset=None, required=False)
    type_id = NamedChoices(label='種別', queryset=None, required=False)
    assignee_id = AdminChoices(label='担当者', queryset=None, required=False)
    priority = forms.MultipleChoiceField(label='優先度', choices=Ticket.PRIORITIES, required=False)
    q = forms.CharField(label='キーワード（タイトル・説明）', max_length=200, required=False)
    page_size = forms.IntegerField(label='1ページの件数', min_value=1, max_value=100, required=False, initial=50)

    def __init__(self, *args, actor, project=None, mine=False, **kwargs):
        super().__init__(*args, **kwargs)
        projects = visible_projects(actor)
        if project:
            projects = projects.filter(pk=project.pk)
        self.fields['project_id'].queryset = projects
        if project:
            self.fields['project_id'].widget = forms.HiddenInput()
            self.fields['project_id'].initial = project.pk
        for name, label, model in (
            ('status_id', 'ステータス', TicketStatus),
            ('type_id', '種別', TicketType),
        ):
            choices = []
            names = set()
            for item in model.objects.filter(project__in=projects).order_by('name', 'pk'):
                if item.name not in names:
                    choices.append((str(item.pk), item.name))
                    names.add(item.name)
            self.fields[name] = forms.MultipleChoiceField(label=label, choices=choices, required=False)
        self.fields['assignee_id'].queryset = User.objects.filter(Q(membership__project__in=projects) | Q(assigned_tickets__project__in=projects)).distinct().order_by('username')
        if mine:
            del self.fields['assignee_id']
        for name, field in self.fields.items():
            if name == 'project_id' and project:
                continue
            if isinstance(field, (forms.MultipleChoiceField, forms.ModelMultipleChoiceField)):
                field.widget = SearchDropdown(attrs={'label': field.label}, choices=field.choices)
