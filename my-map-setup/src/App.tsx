import * as React from 'react';
import { Theme, Flex, Tabs, Select } from '@radix-ui/themes';
import ShortcutsView from './views/ShortcutsView';
import { CourseProvider, useCourse, Course } from './context/CourseContext';
import PolygonEditorView from './views/PolygonEditorView';

function CourseSelector() {
  const { courses, selectedCourse, setSelectedCourse } = useCourse();

  const handleValueChange = (value: string) => {
    const course = courses.find(c => c.id === value) || null;
    setSelectedCourse(course);
  };

  return (
    <div style={{ position: 'absolute', top: 12, left: 12, zIndex: 20 }}>
      {courses.length > 0 && selectedCourse && (
        <Select.Root value={selectedCourse.id} onValueChange={handleValueChange}>
          <Select.Trigger placeholder="Select a course..." />
          <Select.Content>
            <Select.Group>
              {courses.map(course => (
                <Select.Item key={course.id} value={course.id}>
                  {course.name}
                </Select.Item>
              ))}
            </Select.Group>
          </Select.Content>
        </Select.Root>
      )}
    </div>
  );
}


function MainApp() {
  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      <CourseSelector />
      <Tabs.Root defaultValue="shortcuts" style={{height: '100%', display: 'flex', flexDirection: 'column'}}>
        <Tabs.List style={{position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', zIndex: 20}}>
          <Tabs.Trigger value="shortcuts">Shortcuts</Tabs.Trigger>
          <Tabs.Trigger value="polygons">Polygon Editor</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="shortcuts" style={{flexGrow: 1}}>
          <ShortcutsView />
        </Tabs.Content>
        <Tabs.Content value="polygons" style={{flexGrow: 1}}>
            <PolygonEditorView />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  )
}

export default function App() {
  return (
    <Theme accentColor="blue" grayColor="slate" radius="medium" scaling="100%">
      <CourseProvider>
        <MainApp />
      </CourseProvider>
    </Theme>
  );
}