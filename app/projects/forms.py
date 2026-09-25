from django import forms
from accounts.models import User
from .models import Project


class UserChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.display_name}（{obj.username}）'


class AdminChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.display_name}（{obj.username}）'


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows':5})}


class CreateProjectForm(ProjectForm):
    admins = AdminChoices(label='プロジェクト管理者（1名以上・複数選択可）', queryset=User.objects.filter(is_active=True, is_special=False).order_by('username'))


class MemberForm(forms.Form):
    user = UserChoice(label='追加する参加者', queryset=User.objects.none())

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.filter(is_active=True, is_special=False).exclude(membership__project=project).order_by('username')


class RoleForm(forms.Form):
    is_project_admin = forms.BooleanField(label='プロジェクト管理者', required=False)


class MasterForm(forms.Form):
    name = forms.CharField(label='名称', max_length=100)
    is_active = forms.BooleanField(label='有効', required=False, initial=True)
