import { useState } from 'react';
import type { ScanResult } from '../types';
import { artifactUrl } from '../lib/api';
import { EmptyState } from './ui';

export function ScreenshotGallery({ results }: { results: ScanResult[] }) {
  const [active, setActive] = useState<string | null>(null);
  const withArtifacts = results.filter((result) => (result.artifacts ?? []).some((a) => a.screenshot));

  if (withArtifacts.length === 0) {
    return <EmptyState title="Keine Screenshots vorhanden" />;
  }

  return (
    <div className="stack">
      {withArtifacts.map((result) => (
        <div key={result.id} className="stack-sm">
          <h4>
            {result.profile_label} · Runde {result.round}
          </h4>
          <div className="gallery">
            {(result.artifacts ?? [])
              .filter((artifact) => artifact.screenshot)
              .map((artifact) => (
                <figure key={`${result.id}-${artifact.name}`} className="shot">
                  <button type="button" onClick={() => setActive(artifactUrl(artifact.screenshot as string))}>
                    <img
                      src={artifactUrl(artifact.screenshot as string)}
                      alt={`${result.profile_label} – ${artifact.name}`}
                      loading="lazy"
                    />
                  </button>
                  <figcaption>
                    {artifact.name.replace(/^\d+-/, '').replace(/-/g, ' ')}
                    {artifact.html && (
                      <>
                        {' · '}
                        <a href={artifactUrl(artifact.html)} target="_blank" rel="noreferrer">
                          HTML-Snapshot
                        </a>
                      </>
                    )}
                  </figcaption>
                </figure>
              ))}
          </div>
        </div>
      ))}
      {active && (
        <div className="lightbox" role="dialog" aria-modal="true" onClick={() => setActive(null)}>
          <img src={active} alt="Screenshot in Originalgröße" />
          <button type="button" className="lightbox-close" onClick={() => setActive(null)}>
            Schließen
          </button>
        </div>
      )}
    </div>
  );
}
