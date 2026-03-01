[doc](https://pypi.org/project/django-tailwind/)

```bash

pip install 'django-tailwind[cookiecutter,honcho,reload]'

# Then at settings add the tailwind

python manage.py tailwind init
```

```python

# go with default theme , option 2 , y
# add theme to settings install  also

TAILWIND_APP_NAME = "theme"
INTERNAL_IPS = ['127.0.0.1']



NPM_BIN_PATH = r"C:\Program Files\nodejs\npm.cmd"

```

```bash
# to find the npm
where npm

python manage.py tailwind install
```

```html
{% load static tailwind_tags %} ...
<head>
  ... {% tailwind_css %} ...
</head>
```

```bash
python manage.py tailwind start
# To reload automatically each time so add this at settings
django_browser_reload


```

```python

# at this on settings middleware section
"django_browser_reload.middleware.BrowserReloadMiddleware",
# always last at project level url pattern
path("__reload__/", include("django_browser_reload.urls")),

```

```

```

[1] Light , Dark mode note working
[2] Report Must be Done
[3] All the Figures Must be done
[4] Code Understanding and modification must be done
[5] test all the features , reason behind adding it , do all types of test ( unit , function , system , )
