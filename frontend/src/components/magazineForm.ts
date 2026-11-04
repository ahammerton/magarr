import type { Frequency } from '../api/types';
import { t } from '../i18n';

export interface MagazineFormValues {
  title: string;
  alternateTitles: string[];
  publisher: string;
  language: string;
  category: string;
  frequency: Frequency;
  firstIssueYear: number | string;
  tags: string[];
  qualityProfileId: string | null;
  rootFolderId: string | null;
  monitored: boolean;
  posterUrl: string;
  /** YYYY-MM-DD, or blank for no cutoff. */
  searchCutoff: string;
  grabNewSpecials: boolean;
  issueNamingTemplate: string;
  notes: string;
}

export const EMPTY_MAGAZINE: MagazineFormValues = {
  title: '',
  alternateTitles: [],
  publisher: '',
  language: 'en',
  category: '',
  frequency: 'monthly',
  firstIssueYear: '',
  tags: [],
  qualityProfileId: null,
  rootFolderId: null,
  monitored: true,
  posterUrl: '',
  searchCutoff: '',
  grabNewSpecials: false,
  issueNamingTemplate: '',
  notes: '',
};

export const CATEGORIES = [
  'Technology',
  'Science',
  'Gaming',
  'News & Politics',
  'Business',
  'Fashion',
  'Lifestyle',
  'Music',
  'Film & TV',
  'Sport',
  'Motoring',
  'Food & Drink',
  'Travel',
  'Hobbies',
];

export const FREQUENCIES: Frequency[] = ['weekly', 'monthly', 'quarterly', 'ad-hoc'];

const blankToNull = (value: string) => (value.trim() ? value.trim() : null);

/** Shape the form values as an API body. */
export function toMagazineInput(values: MagazineFormValues) {
  return {
    title: values.title.trim(),
    alternateTitles: values.alternateTitles,
    publisher: blankToNull(values.publisher),
    language: values.language.trim() || 'en',
    category: blankToNull(values.category),
    frequency: values.frequency,
    firstIssueYear: values.firstIssueYear === '' ? null : Number(values.firstIssueYear),
    tags: values.tags,
    qualityProfileId: values.qualityProfileId ? Number(values.qualityProfileId) : undefined,
    rootFolderId: values.rootFolderId ? Number(values.rootFolderId) : undefined,
    monitored: values.monitored,
    posterUrl: blankToNull(values.posterUrl),
    searchCutoff: blankToNull(values.searchCutoff),
    grabNewSpecials: values.grabNewSpecials,
    issueNamingTemplate: blankToNull(values.issueNamingTemplate),
    notes: blankToNull(values.notes),
  };
}

export function validateTitle(value: string): string | null {
  return value.trim() ? null : t('magazine.validation.title');
}
