from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()


class EmailUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        # Do not ask for username; we auto-set it from email
        fields = ("email", "first_name", "last_name")
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "you@example.com"}
            ),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            # Password fields are provided by UserCreationForm; update in __init__
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Friendly error messages
        if "email" in self.fields:
            self.fields["email"].error_messages.update({"required": "Email is required"})
        # Ensure password widgets get dark-theme classes
        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update({"class": "form-control"})
        if "password2" in self.fields:
            self.fields["password2"].widget.attrs.update({"class": "form-control"})

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            raise forms.ValidationError("Email is required")
        return email.lower()

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.username:
            user.username = user.email
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AuthenticationForm uses the User model's USERNAME_FIELD for label
        # Apply dark theme classes to inputs
        if "username" in self.fields:
            self.fields["username"].label = "Email"
            self.fields["username"].widget.attrs.update(
                {
                    "class": "form-control",
                    "placeholder": "Email address",
                    "autofocus": True,
                }
            )
        if "password" in self.fields:
            self.fields["password"].widget.attrs.update({"class": "form-control"})
