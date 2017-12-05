import copy
from django import forms
from django.contrib import messages
import hjson
from . import models, auth, factory
from . import tasks
from .const import *
from .models import Project, Data, Analysis, Job, Access
from biostar.accounts.models import Profile, User

# Share the logger with models.
logger = models.logger


def join(*args):
    return os.path.abspath(os.path.join(*args))

class ProjectForm(forms.ModelForm):
    image = forms.ImageField(required=False)

    # Should not edit uid because the data directories get messed up ( for now). 
    uid = forms.CharField(max_length=32, required=False)

    class Meta:
        model = Project
        fields = ['name', 'summary', 'text', 'uid','image', "privacy", "sticky"]


class DataUploadForm(forms.ModelForm):
    # choices = DATA_TYPES.items()
    # data_type = forms.IntegerField(widget=forms.Select(choices=choices))

    file = forms.FileField()

    class Meta:
        model = Data
        fields = ['file', 'summary', 'text', "sticky"]


class DataEditForm(forms.ModelForm):
    # choices = DATA_TYPES.items()
    # data_type = forms.IntegerField(widget=forms.Select(choices=choices))

    class Meta:
        model = Data
        fields = ['name', 'summary', 'text', 'sticky']


class RecipeForm(forms.ModelForm):
    # MAXSIZE in KiloBytes
    MAXSIZE = 100

    class Meta:
        model = Analysis
        fields = ["name", "sticky", "image", "summary", "text" ]

    def clean_image(self):
        cleaned_data = super(RecipeForm, self).clean()
        image = cleaned_data.get('image')

        try:
            if image and image.size > self.MAXSIZE * 1024:
                curr_size = round(image.size/1024)
                raise forms.ValidationError(f"Image file too large: {curr_size}KB should be < {self.MAXSIZE}KB")
        except Exception as exc:
            raise forms.ValidationError(f"Image validation error: {exc}")

        return image




class JobEditForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ['name', "image", 'text', 'sticky']



class ChangeUserAccess(forms.ModelForm):

    user_id = forms.IntegerField(required=True, widget=forms.HiddenInput())
    project_id = forms.IntegerField(required=True, widget=forms.HiddenInput())

    class Meta:
        model = Access
        fields = ['access', 'user_id', "project_id"]


    def clean(self):
        cleaned_data = super(ChangeUserAccess, self).clean()
        project = Project.objects.filter(pk=cleaned_data["project_id"]).first()
        access = [a.access for a in project.access_set.all() if a.user.id!=cleaned_data["user_id"]]
        access.append(cleaned_data["access"])

        if Access.ADMIN_ACCESS not in access:
            raise forms.ValidationError("Alteast one user with Admin Access required.")

    def change_access(self):
        "Change users access to a project"

        user_id = self.cleaned_data["user_id"]
        project_id = self.cleaned_data["project_id"]

        user = User.objects.filter(pk=user_id).first()
        project = Project.objects.filter(pk=project_id).first()

        current = Access.objects.filter(user=user, project=project)
        if current:
            current.update(access=self.cleaned_data.get("access", current.first().access))
            return
        new_access = Access(user=user, project=project,
                            access=self.cleaned_data.get("access", Access.NO_ACCESS))
        new_access.save()


def access_forms(users, project):
    " Generate a list of forms for a given user list"

    forms = []
    for user in users:
        access = Access.objects.filter(user=user, project=project).first()
        initial = dict(access=Access.NO_ACCESS, user_id=user.id)
        if access:
            initial = dict(access=access.access, user_id=user.id)

        access_form = ChangeUserAccess(instance=access, initial=initial)
        forms.append((user,access_form))

    return forms


class DataCopyForm(forms.Form):
    project = forms.IntegerField()

    def __init__(self, current, request, *args, **kwargs):

        self.current = current
        # Needed when a new project is created
        self.user = request.user
        self.request = request

        super().__init__(*args, **kwargs)


    def save(self):

        project = Project.objects.filter(pk=self.cleaned_data["project"]).first()
        name, text, = f"Copy of: {self.current.name}", self.current.text
        summary, data_type = self.current.summary, self.current.data_type
        path = self.current.get_path()

        data = auth.create_data(project=project,user=self.user, name=name,
                                summary=summary, data_type=data_type, path=path,
                                link=True)
        data.save()

        return data

    def clean(self):
        cleaned_data = super(DataCopyForm, self).clean()

        if self.request.user.is_anonymous:
            msg = "You have to be logged in to copy data."
            messages.error(self.request, msg )
            raise forms.ValidationError(msg)

        access = Access.objects.filter(user=self.request.user, project=self.current.project).first()

        # 0 is selected to create a new project.
        if cleaned_data.get("project") == 0:
            new_project = auth.create_project(user=self.user, name="New project")
            # Mutates dict with created id
            cleaned_data["project"] = new_project.id
            messages.success(self.request, f"Created a new project")

        # Can not duplicate into the project if you do not have admin access to it.
        if cleaned_data.get("project") == self.current.project.id:
            if (not access or access.access < Access.ADMIN_ACCESS):
                msg= "Can not duplicate into a project without Admin Access"
                messages.error(self.request, msg )
                raise forms.ValidationError(msg)



class FilesCopyForm(forms.Form):

    paths = forms.CharField(max_length=256)

    def __init__(self, project, job=None, *args, **kwargs):
        self.project = project
        self.job = job
        super().__init__(*args, **kwargs)

    def save(self):
        paths = self.cleaned_data["paths"]
        for path in paths:
            tasks.copier(target_project=self.project.id, fname=path, link=True)
            logger.info(f"Copy data at: {path}")

        return paths

    def clean(self):
        cleaned_data = dict(paths=self.data.getlist('paths', []))
        basedir = '' if not self.job else self.job.path

        for idx,path in enumerate(cleaned_data["paths"]):
            # Figure out the full path based on existing data
            path = path[1:] if path.startswith("/") else path
            path = join(basedir, path)
            if os.path.isfile(path):
                # Mutates paths list
                cleaned_data["paths"][idx] = path
            else:
                raise forms.ValidationError(f"{path} not a file.")

        return cleaned_data


class RecipeCopyForm(forms.Form):
    project = forms.IntegerField()

    def __init__(self, analysis, request, *args, **kwargs):
        self.analysis = analysis

        # Needed when a new project is created
        self.user = request.user
        self.request = request

        super().__init__(*args, **kwargs)

    def save(self):

        project_id = self.cleaned_data.get("project")
        current_project = Project.objects.filter(id=project_id).first()

        current_params = auth.get_analysis_attr(analysis=self.analysis, project=current_project)
        new_analysis = auth.create_analysis(**current_params)
        # Images needs to be set by it set
        new_analysis.image.save(self.analysis.name, self.analysis.image, save=True)
        new_analysis.name = f"Copy of: {self.analysis.name}"
        new_analysis.state = self.analysis.state
        new_analysis.security = self.analysis.security
        new_analysis.save()

        return new_analysis

    def clean(self):

        cleaned_data = super(RecipeCopyForm, self).clean()

        if self.request.user.is_anonymous:
            msg = "You have to be logged in to copy a recipe."
            messages.error(self.request, msg )
            raise forms.ValidationError(msg)

        access = Access.objects.filter(user=self.request.user, project=self.analysis.project).first()

        # 0 is selected to create a new project.
        if cleaned_data.get("project") == 0:

            new_project = auth.create_project(user=self.user, name="New project")
            # Mutates dict with created id
            cleaned_data["project"] = new_project.id
            messages.success(self.request, f"Created a new project")

        # Can not duplicate into the project if you do not have admin access to it.
        if cleaned_data.get("project") == self.analysis.project.id:
            if (not access or access.access < Access.ADMIN_ACCESS):
                msg= "Can not duplicate into a project without Admin Access"
                messages.error(self.request, msg )
                raise forms.ValidationError(msg)

        return cleaned_data


class RecipeInterface(forms.Form):

    # The name of results when running the recipe.
    name = forms.CharField(max_length=256, help_text="This is will be the name of the results.")

    def __init__(self, request, analysis, json_data, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The json data determines what fields does the form have.
        self.json_data = json_data

        # The project is required to select data from.
        self.analysis = analysis
        self.project = analysis.project

        # Get request specific information
        self.request = request
        self.user = self.request.user

        # Create the dynamic field from each key in the data.
        for name, data in self.json_data.items():
            field = factory.dynamic_field(data, self.project)

            # Insert only valid fields.
            if field:
                self.fields[name] = field

    def clean(self):
        cleaned_data = super(RecipeInterface, self).clean()

        if self.user.is_anonymous():
            msg1 = "A user must be logged in to run an analysis."
            raise forms.ValidationError(msg1)

        # Check the permissions for
        entry = Access.objects.filter(user=self.user, project=self.project).first()

        if not entry or entry.access < Access.EXECUTE_ACCESS:
            msg2 = "You don't have exectute rights in this project. Copy this analysis to another project."
            raise forms.ValidationError(msg2)

        if self.analysis.security != Analysis.AUTHORIZED:
            msg3 = "The recipe has been modified. It must be reviewed by a staff member to authorize it."
            raise forms.ValidationError(msg3)

    def fill_json_data(self):
        """
        Produces a filled in JSON data based on user input.
        Should be called after the form has been filled and is valid.
        """

        # Creates a data.id to data mapping.
        store = dict((data.id, data) for data in self.project.data_set.all())

        # Make a copy of the original json data used to render the form.
        json_data = copy.deepcopy(self.json_data)

        # Alter the json data and fill in the extra information.
        for field, item in json_data.items():

            # If the field is a data field then fill in more information.
            if item.get("path") or item.get("link"):
                data_id = int(self.cleaned_data.get(field))
                data = store.get(data_id)

                # This mutates the `item` dictionary!
                data.fill_dict(item)

            # The JSON value will be overwritten with the selected field value.
            if field in self.cleaned_data:
                item["value"] = self.cleaned_data[field]

        return json_data


class EditCode(forms.Form):
    SAVE = "SAVE"

    # Determines what action to perform on the form.
    action = forms.CharField()

    # The script template.
    template = forms.CharField(required=False)

    # The json specification.
    json = forms.CharField(required=False)

    def __init__(self, user, project, *args, **kwargs):
        self.user = user
        self.project = project
        super().__init__(*args, **kwargs)

    def clean_json(self):
        cleaned_data = super(EditCode, self).clean()
        json_text = cleaned_data.get("json")
        try:
            hjson.loads(json_text)
        except Exception as exc:
            msg = f"Invalid json: {exc}"
            raise forms.ValidationError(msg)
        return json_text

    def clean(self):
        cleaned_data = super(EditCode, self).clean()
        action = cleaned_data.get("action")

        if action == self.SAVE:
            msg = "You don't have sufficient access rights to overwrite this entry."
            if self.user.is_anonymous():
                raise forms.ValidationError(msg)
            entry = Access.objects.filter(user=self.user, project=self.project).first()
            if not entry or entry.access < Access.EDIT_ACCESS:
                raise forms.ValidationError(msg)
