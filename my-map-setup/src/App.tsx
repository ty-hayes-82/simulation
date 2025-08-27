import * as React from 'react';
import { Theme, Select } from '@radix-ui/themes';
import ShortcutsView from './views/ShortcutsView';
import { CourseProvider, useCourse, Course } from './context/CourseContext';

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
      <div style={{ height: '100%', width: '100%' }}>
        <ShortcutsView />
      </div>
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