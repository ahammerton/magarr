import { AspectRatio, Center, Image, Paper, Text } from '@mantine/core';
import { useEffect, useState } from 'react';

import { apiBlob } from '../api/client';

function initials(title: string): string {
  return title
    .split(/\s+/)
    .filter((word) => /^[\p{L}\p{N}]/u.test(word))
    .slice(0, 3)
    .map((word) => word[0]!.toUpperCase())
    .join('');
}

/** Object URL for an API image; null until it loads or if it can't be loaded. */
function useApiImage(path: string | null): string | null {
  // Remembered with the path it belongs to, so a previous image never shows for a new path.
  const [loaded, setLoaded] = useState<{ path: string; url: string } | null>(null);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let created: string | null = null;
    apiBlob(path, controller.signal)
      .then((blob) => {
        created = URL.createObjectURL(blob);
        setLoaded({ path, url: created });
      })
      .catch(() => {
        // No readable cover: the initials stay.
      });
    return () => {
      controller.abort();
      if (created) URL.revokeObjectURL(created);
    };
  }, [path]);
  return loaded && loaded.path === path ? loaded.url : null;
}

interface PosterProps {
  title: string;
  /** Poster set by the user. */
  url: string | null;
  /** Cover of the first downloaded issue, used when there's no poster. */
  coverUrl?: string | null;
  width?: number | string;
}

/** Cover image at 2:3, falling back to the first issue's cover, then the title's initials. */
export function Poster({ title, url, coverUrl = null, width = '100%' }: PosterProps) {
  const [failed, setFailed] = useState(false);
  const usePoster = Boolean(url) && !failed;
  const cover = useApiImage(usePoster ? null : coverUrl);
  const src = usePoster ? url : cover;
  return (
    <AspectRatio ratio={2 / 3} w={width}>
      {src ? (
        <Image src={src} alt={title} radius="sm" fit="cover" onError={() => usePoster && setFailed(true)} />
      ) : (
        <Paper radius="sm" bg="var(--mantine-color-violet-light)" aria-label={title}>
          <Center h="100%">
            <Text fw={700} size="xl" c="violet.3">
              {initials(title)}
            </Text>
          </Center>
        </Paper>
      )}
    </AspectRatio>
  );
}
