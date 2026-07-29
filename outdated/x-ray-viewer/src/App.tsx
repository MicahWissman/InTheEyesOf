import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { XRayViewer } from './components/XRayViewer';

interface RecordingConfig {
  id: string;
  title: string;
  anchorsFile: string;
  pointCloudFile: string;
}

interface Manifest {
  recordings: RecordingConfig[];
}

export default function App() {
  const [recordings, setRecordings] = useState<RecordingConfig[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const param = params.get('recording');
    if (param) setSelectedId(param);
  }, []);

  useEffect(() => {
    fetch('/recordings/manifest.json')
      .then((r) => r.json())
      .then((data: Manifest) => setRecordings(data.recordings))
      .catch(() => setError(true));
  }, []);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set('recording', id);
    window.history.pushState({}, '', url);
  };

  if (error) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-[#0a0a0a] px-6">
        <div className="text-center space-y-2">
          <p className="text-red-400 font-mono text-sm">
            Could not load recordings/manifest.json
          </p>
          <p className="text-white/30 font-mono text-xs">
            Ensure the file exists in x-ray-viewer/public/recordings/
          </p>
        </div>
      </div>
    );
  }

  if (recordings.length === 0) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-[#0a0a0a]">
        <Loader2 className="w-6 h-6 text-orange-500 animate-spin" />
      </div>
    );
  }

  const selected = recordings.find((r) => r.id === selectedId) ?? null;

  // Recording picker screen
  if (!selected) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-[#0a0a0a] px-6">
        <div className="w-full max-w-sm bg-[#151619] border border-white/10 rounded-2xl p-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 bg-orange-500 rounded-xl flex items-center justify-center text-black font-black text-sm flex-shrink-0">
              A
            </div>
            <div>
              <h1 className="text-white font-bold text-lg leading-none">InTheEyesOf</h1>
              <p className="text-white/40 text-xs mt-0.5 font-mono">X-Ray Viewer</p>
            </div>
          </div>
          <p className="text-white/40 text-sm mb-4 font-mono">Select a recording</p>
          <div className="space-y-2">
            {recordings.map((r) => (
              <button
                key={r.id}
                onClick={() => handleSelect(r.id)}
                className="w-full text-left bg-white/5 active:bg-white/15 border border-white/10 hover:border-orange-500/30 rounded-xl px-4 py-3.5 transition-all"
              >
                <span className="block text-white font-medium text-sm">{r.title}</span>
                <span className="block text-white/30 font-mono text-xs mt-0.5">{r.id}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-screen h-screen overflow-hidden bg-[#0a0a0a] flex flex-col">
      {recordings.length > 1 && (
        <div className="flex-shrink-0 flex items-center gap-3 px-4 py-2 bg-black/60 border-b border-white/10 z-10">
          <span className="text-white/30 font-mono text-[10px] uppercase tracking-wider">
            Recording
          </span>
          <select
            value={selected.id}
            onChange={(e) => handleSelect(e.target.value)}
            className="bg-white/5 text-white border border-white/10 rounded-lg px-3 py-1 text-sm font-mono focus:outline-none focus:border-orange-500/50 flex-1 min-w-0"
          >
            {recordings.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="flex-1 relative min-h-0">
        <XRayViewer
          key={selected.id}
          title={selected.title}
          anchorsUrl={`/recordings/${selected.id}/${selected.anchorsFile}`}
          pointCloudUrl={`/recordings/${selected.id}/${selected.pointCloudFile}`}
        />
      </div>
    </div>
  );
}
