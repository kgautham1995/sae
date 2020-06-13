from django import forms
from website.models import ContactusModel

class contactusForm(forms.ModelForm):
    class Meta:
        model = ContactusModel
        fields = "__all__"
    # Name = forms.CharField(label="NAME")
    # Email = forms.EmailField(label="EMAIL ID")
    # ContactNo = forms.IntegerField(label="CONTACT NO")
    # Message = forms.CharField(label="MESSAGE")