import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { EmptyPage } from './components/EmptyPage';
import { HistoryPage } from './pages/activity/HistoryPage';
import { ManualImportPage } from './pages/activity/ManualImportPage';
import { CalendarPage } from './pages/calendar/CalendarPage';
import { QueuePage } from './pages/activity/QueuePage';
import { AddMagazinePage } from './pages/library/AddMagazinePage';
import { ImportCsvPage } from './pages/library/ImportCsvPage';
import { MagazineIndexPage } from './pages/library/MagazineIndexPage';
import { UnmappedPage } from './pages/library/UnmappedPage';
import { MagazineDetailPage } from './pages/magazine/MagazineDetailPage';
import { AutomationPage } from './pages/settings/AutomationPage';
import { DownloadClientsPage } from './pages/settings/DownloadClientsPage';
import { IndexersPage } from './pages/settings/IndexersPage';
import { MediaManagementPage } from './pages/settings/MediaManagementPage';
import { NotificationsPage } from './pages/settings/NotificationsPage';
import { ProfilesPage } from './pages/settings/ProfilesPage';
import { BackupPage } from './pages/system/BackupPage';
import { HealthPage } from './pages/system/HealthPage';
import { LogsPage } from './pages/system/LogsPage';
import { StatusPage } from './pages/system/StatusPage';
import { TasksPage } from './pages/system/TasksPage';
import { WantedPage } from './pages/wanted/WantedPage';

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/library" replace />} />
        <Route path="library" element={<MagazineIndexPage />} />
        <Route path="library/add" element={<AddMagazinePage />} />
        <Route path="library/import" element={<ImportCsvPage />} />
        <Route path="library/unmapped" element={<UnmappedPage />} />
        <Route path="magazine/:id" element={<MagazineDetailPage />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="activity" element={<Navigate to="/activity/queue" replace />} />
        <Route path="activity/queue" element={<QueuePage />} />
        <Route path="activity/history" element={<HistoryPage />} />
        <Route path="activity/import" element={<ManualImportPage />} />
        <Route path="wanted" element={<WantedPage />} />
        <Route path="settings" element={<Navigate to="/settings/mediamanagement" replace />} />
        <Route path="settings/mediamanagement" element={<MediaManagementPage />} />
        <Route path="settings/profiles" element={<ProfilesPage />} />
        <Route path="settings/indexers" element={<IndexersPage />} />
        <Route path="settings/downloadclients" element={<DownloadClientsPage />} />
        <Route path="settings/automation" element={<AutomationPage />} />
        <Route path="settings/notifications" element={<NotificationsPage />} />
        <Route path="system" element={<Navigate to="/system/status" replace />} />
        <Route path="system/status" element={<StatusPage />} />
        <Route path="system/health" element={<HealthPage />} />
        <Route path="system/tasks" element={<TasksPage />} />
        <Route path="system/backup" element={<BackupPage />} />
        <Route path="system/logs" element={<LogsPage />} />
        <Route
          path="*"
          element={<EmptyPage title="page.notFound.title" description="page.notFound.description" />}
        />
      </Route>
    </Routes>
  );
}
