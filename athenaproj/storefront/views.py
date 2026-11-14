from django.core.paginator import Paginator
from django.http import Http404
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Study
from core.services import (
    category_tiles,
    get_public_study,
    popular_studies,
    search_studies,
    for_you_feed,
    personal_row,
    profile_ready,
    refresh_interest_predictions,
    save_profile,
    add_to_shortlist,
    compare_studies,
    remove_from_shortlist,
    shortlist_for,
)

from .forms import StudyFilterForm
from .forms import ProfileForm
from .decorators import participant_required


def home(request):
    personal_items = []
    if (
        request.user.is_authenticated
        and hasattr(request.user, 'participant_profile')
        and profile_ready(request.user.participant_profile)
    ):
        personal_items = personal_row(request.user.participant_profile)
    return render(
        request,
        'storefront/home.html',
        {
            'category_tiles': category_tiles(),
            'popular_studies': popular_studies(),
            'personal_items': personal_items,
        },
    )


def studies(request):
    form = StudyFilterForm(request.GET)
    form.is_valid()
    cleaned = form.cleaned_data
    queryset = search_studies(
        q=cleaned.get('q', ''),
        category=cleaned.get('category', ''),
        types=cleaned.get('type'),
        region=cleaned.get('region', ''),
        duration=cleaned.get('duration', ''),
        hv=cleaned.get('hv', False),
        comp=cleaned.get('comp', ''),
        sort=cleaned.get('sort') or 'newest',
    )
    page_obj = Paginator(queryset, 12).get_page(request.GET.get('page'))
    return render(
        request,
        'storefront/studies.html',
        {'form': form, 'page_obj': page_obj, 'result_count': queryset.count()},
    )


def study_detail(request, slug):
    try:
        study = get_public_study(slug)
    except Study.DoesNotExist:
        raise Http404
    is_shortlisted = (
        request.user.is_authenticated
        and hasattr(request.user, 'participant_profile')
        and study.shortlists.filter(
            participant=request.user.participant_profile
        ).exists()
    )
    return render(
        request,
        'storefront/study_detail.html',
        {'study': study, 'is_shortlisted': is_shortlisted},
    )


def _safe_next(request, fallback):
    next_url = request.POST.get('next', '')
    if next_url.startswith('/') and not next_url.startswith('//'):
        return next_url
    return fallback


@participant_required
def shortlist(request):
    profile = request.user.participant_profile
    return render(request, 'storefront/shortlist.html', {
        'studies': shortlist_for(profile),
    })


@require_POST
@participant_required
def shortlist_add(request, study_id):
    study = Study.objects.filter(pk=study_id).first()
    fallback = (
        reverse('storefront:study_detail', kwargs={'slug': study.slug})
        if study is not None else '/shortlist/'
    )
    try:
        _, created = add_to_shortlist(request.user.participant_profile, study_id)
    except Study.DoesNotExist:
        return redirect(_safe_next(request, fallback))
    messages.success(
        request,
        'Saved to your shortlist.' if created else 'Already on your shortlist.',
    )
    return redirect(_safe_next(request, fallback))


@require_POST
@participant_required
def shortlist_remove(request, study_id):
    remove_from_shortlist(request.user.participant_profile, study_id)
    messages.success(request, 'Removed from your shortlist.')
    study = Study.objects.filter(pk=study_id).first()
    fallback = (
        reverse('storefront:study_detail', kwargs={'slug': study.slug})
        if study is not None else '/shortlist/'
    )
    return redirect(_safe_next(request, fallback))


@participant_required
def shortlist_compare(request):
    try:
        studies = compare_studies(
            request.user.participant_profile,
            request.GET.getlist('ids'),
        )
    except ValueError:
        messages.error(
            request,
            'Choose two or three studies from your shortlist to compare',
        )
        return redirect('/shortlist/')
    return render(request, 'storefront/compare.html', {'studies': studies})


def support(request):
    faq_items = [
        (
            'Who can take part in a study?',
            'Each study has its own eligibility rules, such as age, health and visit requirements. Read the study page carefully before deciding whether it suits you.',
        ),
        (
            'Do I have to pay anything?',
            'No. You do not pay to take part in an Athena study. Any costs and support are explained on the study page.',
        ),
        (
            'How do I apply?',
            'Choose a study and select Check if I can apply. You will sign in or create an account, then answer the study questions.',
        ),
        (
            'What happens after I apply?',
            'The research team reviews your answers against the study requirements. They will contact you with the next steps if you may be eligible.',
        ),
        (
            'Can I withdraw?',
            'Yes. You can withdraw from a study at any time. Tell the research team as soon as possible so they can explain what happens next.',
        ),
        (
            'How does compensation work?',
            'Some studies provide compensation for your time and travel. Where the amount is approved for display, it is shown on the study page.',
        ),
        (
            'How is my health information used?',
            'Your information is used to check eligibility and run the study. The research team explains how it is protected and used in the study information.',
        ),
        (
            'Who runs the studies on Athena?',
            'Studies are run by partner hospitals, universities, research institutes, sponsors and clinical research organisations. The organisation is named on each study page.',
        ),
    ]
    return render(request, 'storefront/support.html', {'faq_items': faq_items})


@participant_required
def onboarding(request):
    profile = request.user.participant_profile
    form = ProfileForm(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        was_ready = profile_ready(profile)
        save_profile(profile, form)
        refresh_interest_predictions(profile)
        messages.success(
            request, 'Your profile is updated.' if was_ready else 'Your profile is saved.'
        )
        return redirect('/for-you/' if not was_ready else '/account/')
    return render(request, 'storefront/onboarding.html', {
        'form': form, 'editing': profile.onboarding_completed_at is not None,
    })


@participant_required
def for_you(request):
    profile = request.user.participant_profile
    if not profile_ready(profile):
        messages.info(request, 'Complete your profile first.')
        return redirect('/onboarding/')
    return render(request, 'storefront/for_you.html', for_you_feed(profile))
