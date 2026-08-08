import { useEffect, useState, type ComponentType } from 'react';

type ModuleMap = Record<string, () => Promise<Record<string, unknown>>>;

// The default sandbox entry imports a generated registry
// (./.generated/mockup-components) populated by a Vite plugin. This
// per-design-system entry instead discovers its own mockups directly with
// import.meta.glob, so it needs no plugin or generated file.
const modules = import.meta.glob('./mockups/**/*.tsx') as ModuleMap;

function _resolveComponent(
  mod: Record<string, unknown>,
  name: string,
): ComponentType | undefined {
  const fns = Object.values(mod).filter(
    (v) => typeof v === 'function',
  ) as ComponentType[];
  return (
    (mod.default as ComponentType) ||
    (mod.Preview as ComponentType) ||
    (mod[name] as ComponentType) ||
    fns[fns.length - 1]
  );
}

function PreviewRenderer({
  componentPath,
  modules,
}: {
  componentPath: string;
  modules: ModuleMap;
}) {
  const [Component, setComponent] = useState<ComponentType | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setComponent(null);
    setError(null);

    async function loadComponent(): Promise<void> {
      const key = `./mockups/${componentPath}.tsx`;
      const loader = modules[key];
      if (!loader) {
        setError(`No component found at ${componentPath}.tsx`);
        return;
      }

      try {
        const mod = await loader();
        if (cancelled) {
          return;
        }
        const name = componentPath.split('/').pop()!;
        const comp = _resolveComponent(mod, name);
        if (!comp) {
          setError(
            `No exported React component found in ${componentPath}.tsx\n\nMake sure the file has at least one exported function component.`,
          );
          return;
        }
        setComponent(() => comp);
      } catch (e) {
        if (cancelled) {
          return;
        }

        const message = e instanceof Error ? e.message : String(e);
        setError(`Failed to load preview.\n${message}`);
      }
    }

    void loadComponent();

    return () => {
      cancelled = true;
    };
  }, [componentPath, modules]);

  if (error) {
    return (
      <pre style={{ color: 'red', padding: '2rem', fontFamily: 'system-ui' }}>
        {error}
      </pre>
    );
  }

  if (!Component) return null;

  return <Component />;
}

function Gallery() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <h1 className="text-2xl font-semibold text-gray-900 mb-3">
          Component Preview Server
        </h1>
        <p className="text-gray-500 mb-4">
          This server renders individual components for the workspace canvas.
        </p>
        <p className="text-sm text-gray-400">
          Access component previews at{' '}
          <code className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
            #/ComponentName
          </code>
        </p>
      </div>
    </div>
  );
}

// The default entry parses a path-based /preview/{path} route served by the dev
// plugin. This static secondary entry has no such server route, so it reads the
// preview target from the URL hash (`#/Foo` or `#/nested/Foo`) instead.
function getPreviewPath(): string | null {
  const path = window.location.hash.replace(/^#\/?/, '').replace(/\/$/, '');
  return path.length > 0 ? path : null;
}

function App() {
  const [previewPath, setPreviewPath] = useState<string | null>(
    getPreviewPath(),
  );

  // Hash-only URL changes don't reload the iframe, so react to hashchange.
  useEffect(() => {
    const onHashChange = () => setPreviewPath(getPreviewPath());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  if (previewPath) {
    return <PreviewRenderer componentPath={previewPath} modules={modules} />;
  }

  return <Gallery />;
}

export default App;
