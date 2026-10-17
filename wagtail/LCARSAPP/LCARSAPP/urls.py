from django.conf import settings
from django.urls import include, path
from django.contrib import admin

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from search import views as search_views
from .api import api_router
from missions import api as missions_api

urlpatterns = [
    path('django-admin/', admin.site.urls),

    path('admin/', include(wagtailadmin_urls)),
    path('documents/', include(wagtaildocs_urls)),

    path('search/', search_views.search, name='search'),

    path('api/v2/', api_router.urls),
    path('api/missions/session/', missions_api.session),
    path('api/missions/', missions_api.mission_list),
    path('api/missions/<int:pk>/', missions_api.mission_detail),
    path('api/gates/<int:pk>/decide/', missions_api.decide_gate),
    path('api/crew/status/', missions_api.crew_status),
    path('api/crew/model/start/', missions_api.start_model),
    path('api/crew/model/stop/', missions_api.stop_model),
    path('api/crew/fetch/', missions_api.fetch_data),
    path('api/missions/launch/', missions_api.launch_mission),

]


if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns = urlpatterns + [
    # For anything not caught by a more specific rule above, hand over to
    # Wagtail's page serving mechanism. This should be the last pattern in
    # the list:
    path("", include(wagtail_urls)),

    # Alternatively, if you want Wagtail pages to be served from a subpath
    # of your site, rather than the site root:
    #    path("pages/", include(wagtail_urls)),
]
