from django import forms
from django.contrib.auth.validators import UnicodeUsernameValidator


class LoginForm(forms.Form):
    username = forms.CharField(label='ユーザーID', max_length=150)
    password = forms.CharField(label='パスワード', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))


class PasswordForm(forms.Form):
    old_password = forms.CharField(label='現在のパスワード', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    new_password = forms.CharField(label='新パスワード（12文字以上）', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    confirm_password = forms.CharField(label='新パスワード（確認）', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def clean(self):
        data = super().clean()
        if data.get('new_password') != data.get('confirm_password'):
            self.add_error('confirm_password', '新パスワードが一致しません。')
        return data


class UserForm(forms.Form):
    username = forms.CharField(label='ユーザーID', max_length=150, validators=[UnicodeUsernameValidator()])
    display_name = forms.CharField(label='表示名', max_length=150)
    is_system_admin = forms.BooleanField(label='システム管理者', required=False)
