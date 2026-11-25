// Dev-only review page (http://localhost:5173/?gallery): every procedural model type side by side.
// Generate the models first:  cd backend && python -m scripts.model_gallery
import { Suspense, useEffect, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { ContactShadows, Environment, Html, Lightformer, OrbitControls, useGLTF } from '@react-three/drei'

interface Entry {
  i: number
  label: string
  w: number
  d: number
  h: number
}

const COLS = 7
const SPACING = 2.9

function Model({ entry, col, row }: { entry: Entry; col: number; row: number }) {
  const gltf = useGLTF(`/static/models/gallery/${entry.i}.glb`, false)
  return (
    <group position={[col * SPACING, 0, row * SPACING]}>
      <primitive object={gltf.scene.clone(true)} />
      <Html position={[0, 0.02, entry.d / 200 + 0.35]} center style={{ pointerEvents: 'none', whiteSpace: 'nowrap' }}>
        <span style={{ fontSize: 12, background: 'rgba(255,255,255,.9)', padding: '1px 6px', borderRadius: 4, direction: 'rtl' }}>
          {entry.label}
        </span>
      </Html>
    </group>
  )
}

export default function ModelGallery() {
  const [entries, setEntries] = useState<Entry[] | null>(null)
  useEffect(() => {
    fetch('/static/models/gallery/index.json')
      .then((r) => r.json())
      .then(setEntries)
      .catch(() => setEntries([]))
  }, [])
  const rows = entries ? Math.ceil(entries.length / COLS) : 1
  // ?gallery&row=N frames a single row up close (for visual review)
  const focusRow = new URLSearchParams(window.location.search).get('row')
  const cx = (COLS * SPACING) / 2 - 1.5
  const camPos: [number, number, number] =
    focusRow !== null ? [cx, 3.2, Number(focusRow) * SPACING + 7.2] : [cx, 13, rows * SPACING + 11]
  const camTarget: [number, number, number] =
    focusRow !== null ? [cx, 0.5, Number(focusRow) * SPACING] : [cx, 0.2, (rows * SPACING) / 2 - 1.5]
  return (
    <div style={{ position: 'fixed', inset: 0, background: '#dfe6ee' }}>
      {entries && entries.length === 0 && <p style={{ padding: 20 }}>Run: cd backend && python -m scripts.model_gallery</p>}
      <Canvas shadows camera={{ position: camPos, fov: 45 }} gl={{ preserveDrawingBuffer: true }}>
        <color attach="background" args={['#e9edf2']} />
        <hemisphereLight args={['#ffffff', '#d9d3c7', 0.7]} />
        <directionalLight position={[6, 12, 8]} intensity={1.6} castShadow />
        <Environment resolution={256}>
          <Lightformer form="rect" intensity={2.2} position={[0, 6, -6]} scale={[14, 6, 1]} />
          <Lightformer form="rect" intensity={1.4} position={[-6, 4, 4]} scale={[6, 6, 1]} />
          <Lightformer form="rect" intensity={1.2} position={[6, 3, 5]} scale={[6, 4, 1]} />
        </Environment>
        <mesh rotation-x={-Math.PI / 2} position={[(COLS * SPACING) / 2 - 1.5, -0.001, (rows * SPACING) / 2 - 1]} receiveShadow>
          <planeGeometry args={[COLS * SPACING + 4, rows * SPACING + 4]} />
          <meshStandardMaterial color="#f1ece4" roughness={1} />
        </mesh>
        <Suspense fallback={null}>
          {entries?.map((e, n) => (
            <Model key={e.i} entry={e} col={n % COLS} row={Math.floor(n / COLS)} />
          ))}
        </Suspense>
        <ContactShadows position={[0, 0.002, 0]} opacity={0.35} scale={60} blur={2.2} far={3} />
        <OrbitControls target={camTarget} makeDefault />
      </Canvas>
    </div>
  )
}
