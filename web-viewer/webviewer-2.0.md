Here is what I did:

1.  Created <NarrativeViewer> Component: I extracted all the 3D logic, Canvas,
    point cloud, and sidebar from App.tsx into a new, reusable component at
    src/components/NarrativeViewer.tsx. This component accepts title, anchorsUrl,
    and pointCloudUrl as props.
2.  Fixed Sidebar State: I updated Sidebar.tsx to stop using the global
    window.clearSelection hack, so clicking on an anchor in one viewer won't
    interfere with the state of another viewer.
3.  Updated App.tsx Configuration: I set up App.tsx to render an array of
    configurations. It iterates through the list and generates a
    <NarrativeViewer> instance for each.
4.  Updated CSS Layout: I added a .multi-viewer-container flexbox layout in
    App.css so that if you have multiple viewers active, they will neatly stack
    side-by-side on your screen.

How to View Multiple Outputs Simultaneously
To show more recordings on the screen, all you need to do is:

1.  Copy the output files from your other pipeline runs into web-viewer/public/
    (e.g., name them narrative_anchors_2.json and gaze_heatmap_2.ply).
2.  Open web-viewer/src/App.tsx and un-comment/add a new configuration object to
    the viewers array:


    1 function App() {
    2   const viewers = [
    3     {
    4       id: 'viewer-1',
    5       title: 'Recording 1: Lobby Walkthrough',
    6       anchorsUrl: '/narrative_anchors.json',
    7       pointCloudUrl: '/gaze_aligned_cleaned.ply'
    8     },
    9     {

10 id: 'viewer-2',
11 title: 'Recording 2: Lab Walkthrough',
12 anchorsUrl: '/narrative_anchors_2.json',
13 pointCloudUrl: '/gaze_heatmap_2.ply' // Add your second PLY
14 },
15 // Add as many as you need!
16 ];
17 // ...

When you start the app with npm run dev, it will automatically divide the screen
and render them side-by-side with fully independent 3D controls and sidebars.
