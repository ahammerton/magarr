import { Autocomplete, NumberInput, Select, Switch, TagsInput, TextInput, Textarea } from '@mantine/core';
import type { UseFormReturnType } from '@mantine/form';

import { t } from '../i18n';
import { CATEGORIES, FREQUENCIES, type MagazineFormValues } from './magazineForm';

type Form = UseFormReturnType<MagazineFormValues>;

export function DetailsFields({ form }: { form: Form }) {
  return (
    <>
      <TextInput
        label={t('magazine.field.title')}
        withAsterisk
        data-autofocus
        {...form.getInputProps('title')}
      />
      <TagsInput
        label={t('magazine.field.alternateTitles')}
        description={t('magazine.field.alternateTitles.hint')}
        {...form.getInputProps('alternateTitles')}
      />
      <TextInput label={t('magazine.field.publisher')} {...form.getInputProps('publisher')} />
      <Autocomplete
        label={t('magazine.field.category')}
        data={CATEGORIES}
        {...form.getInputProps('category')}
      />
      <TextInput
        label={t('magazine.field.language')}
        description={t('magazine.field.language.hint')}
        maxLength={16}
        {...form.getInputProps('language')}
      />
    </>
  );
}

interface SettingsFieldsProps {
  form: Form;
  rootFolders: { value: string; label: string }[];
  profiles: { value: string; label: string }[];
  showNamingTemplate?: boolean;
}

export function SettingsFields({ form, rootFolders, profiles, showNamingTemplate }: SettingsFieldsProps) {
  return (
    <>
      <Select
        label={t('magazine.field.frequency')}
        data={FREQUENCIES.map((f) => ({ value: f, label: t(`frequency.${f}`) }))}
        allowDeselect={false}
        {...form.getInputProps('frequency')}
      />
      <NumberInput
        label={t('magazine.field.firstIssueYear')}
        min={1600}
        max={2200}
        allowDecimal={false}
        {...form.getInputProps('firstIssueYear')}
      />
      <Select
        label={t('magazine.field.rootFolder')}
        data={rootFolders}
        allowDeselect={false}
        {...form.getInputProps('rootFolderId')}
      />
      <Select
        label={t('magazine.field.qualityProfile')}
        data={profiles}
        allowDeselect={false}
        {...form.getInputProps('qualityProfileId')}
      />
      <TagsInput label={t('magazine.field.tags')} {...form.getInputProps('tags')} />
      <TextInput
        type="date"
        label={t('magazine.field.searchCutoff')}
        description={t('magazine.field.searchCutoff.hint')}
        {...form.getInputProps('searchCutoff')}
      />
      <TextInput
        label={t('magazine.field.posterUrl')}
        placeholder="https://"
        {...form.getInputProps('posterUrl')}
      />
      {showNamingTemplate && (
        <TextInput
          label={t('magazine.field.namingTemplate')}
          description={t('magazine.field.namingTemplate.hint')}
          placeholder="{magazine_title} - Issue {issue_number}"
          {...form.getInputProps('issueNamingTemplate')}
        />
      )}
      <Textarea label={t('magazine.field.notes')} autosize minRows={2} {...form.getInputProps('notes')} />
      <Switch
        label={t('magazine.field.monitored')}
        description={t('magazine.field.monitored.hint')}
        {...form.getInputProps('monitored', { type: 'checkbox' })}
      />
      <Switch
        label={t('magazine.field.grabNewSpecials')}
        description={t('magazine.field.grabNewSpecials.hint')}
        {...form.getInputProps('grabNewSpecials', { type: 'checkbox' })}
      />
    </>
  );
}
