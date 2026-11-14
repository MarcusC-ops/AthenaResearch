from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from core.models import Study
from core.services import (
    category_tiles,
    get_public_study,
    popular_studies,
    search_studies,
)

from .forms import StudyFilterForm


def home(request):
    return render(
        request,
        'storefront/home.html',
        {'category_tiles': category_tiles(), 'popular_studies': popular_studies()},
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
    return render(request, 'storefront/study_detail.html', {'study': study})


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
