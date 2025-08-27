import * as React from 'react';

export interface HolePolygon {
  type: 'Feature';
  properties: {
    hole: number;
    area_m2: number;
  };
  geometry: {
    type: 'Polygon';
    coordinates: number[][][];
  };
}

export interface CourseData {
  type: 'FeatureCollection';
  name: string;
  features: HolePolygon[];
}

export interface Course {
  id: string;
  name: string;
  data?: CourseData;
}

export interface CourseContextType {
  courses: Course[];
  selectedCourse: Course | null;
  setSelectedCourse: (course: Course | null) => void;
  updateCourseData: (courseId: string, data: CourseData) => Promise<void>;
  setLocalCourseData: (data: CourseData) => void;
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

  const loadCourseData = async (course: Course): Promise<Course> => {
    try {
      const response = await fetch(`/courses/${course.id}/holes_geofenced.geojson`);
      if (response.ok) {
        const data = await response.json();
        return { ...course, data };
      }
    } catch (error) {
      console.error(`Failed to load data for course ${course.id}:`, error);
    }
    return course;
  };

  const updateCourseData = async (courseId: string, data: CourseData) => {
    try {
      const response = await fetch(`/api/save-course/${courseId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        throw new Error('Failed to save course data');
      }

      // Update state only after successful save
      setCourses(prevCourses =>
        prevCourses.map(course =>
          course.id === courseId ? { ...course, data } : course
        )
      );

      if (selectedCourse?.id === courseId) {
        setSelectedCourse(prev => prev ? { ...prev, data } : null);
      }
    } catch (error) {
      console.error(`Failed to save data for course ${courseId}:`, error);
      throw error; // Re-throw to be caught by the calling component
    }
  };

  const setLocalCourseData = (data: CourseData) => {
    if (selectedCourse) {
      const courseId = selectedCourse.id;
      setCourses(prevCourses =>
        prevCourses.map(course =>
          course.id === courseId ? { ...course, data } : course
        )
      );
      setSelectedCourse(prev => prev ? { ...prev, data } : null);
    }
  };

  const setSelectedCourseWithData = async (course: Course | null) => {
    if (course && !course.data) {
      const courseWithData = await loadCourseData(course);
      setSelectedCourse(courseWithData);
      
      // Update the course in the courses array
      setCourses(prevCourses => 
        prevCourses.map(c => c.id === course.id ? courseWithData : c)
      );
    } else {
      setSelectedCourse(course);
    }
  };

  React.useEffect(() => {
    fetch('/manifest.json')
      .then(res => res.json())
      .then(data => {
        const courseList = data.courses || [];
        setCourses(courseList);
        if (courseList.length > 0) {
          setSelectedCourseWithData(courseList[0]);
        }
      })
      .catch(console.error);
  }, []);

  const value = {
    courses,
    selectedCourse,
    setSelectedCourse: setSelectedCourseWithData,
    updateCourseData,
    setLocalCourseData,
  };

  return <CourseContext.Provider value={value}>{children}</CourseContext.Provider>;
}
