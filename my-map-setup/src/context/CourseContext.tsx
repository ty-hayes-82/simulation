import * as React from 'react';

export interface Course {
  id: string;
  name: string;
}

export interface CourseContextType {
  courses: Course[];
  selectedCourse: Course | null;
  setSelectedCourse: (course: Course | null) => void;
}

export const CourseContext = React.createContext<CourseContextType | null>(null);

export function useCourse() {
  const context = React.useContext(CourseContext);
  if (!context) {
    throw new Error('useCourse must be used within a CourseProvider');
  }
  return context;
}

export function CourseProvider({ children }: { children: React.ReactNode }) {
  const [courses, setCourses] = React.useState<Course[]>([]);
  const [selectedCourse, setSelectedCourse] = React.useState<Course | null>(null);

  React.useEffect(() => {
    fetch('/manifest.json')
      .then(res => res.json())
      .then(data => {
        const courseList = data.courses || [];
        setCourses(courseList);
        if (courseList.length > 0) {
          setSelectedCourse(courseList[0]);
        }
      })
      .catch(console.error);
  }, []);

  const value = {
    courses,
    selectedCourse,
    setSelectedCourse,
  };

  return <CourseContext.Provider value={value}>{children}</CourseContext.Provider>;
}
