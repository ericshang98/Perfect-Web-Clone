import { ReactNode } from 'react';

// image props for image component
export interface Image {
  src: string;
  alt?: string;
  width?: number;
  height?: number;
  className?: string;
}

// brand props for brand component, contains logo and brand title
export interface Brand {
  title?: string;
  description?: string;
  logo?: Image;
  url?: string;
  target?: string;
  className?: string;
}

// nav item props for nav component
export interface NavItem {
  id?: string;
  name?: string;
  title?: string;
  text?: string;
  description?: string;
  url?: string;
  target?: string;
  type?: string;
  icon_url?: string;
  icon?: string | ReactNode;
  badge?: string;
  image?: Image;
  is_expand?: boolean;
  is_active?: boolean;
  is_disabled?: boolean;
  children?: NavItem[];
  className?: string;
}

// nav props for nav component
export interface Nav {
  id?: string;
  title?: string;
  items: NavItem[];
  className?: string;
}

// button props for button component
export interface Button extends NavItem {
  size?: 'default' | 'sm' | 'lg' | 'icon';
  variant?: 'default' | 'outline' | 'ghost' | 'link' | 'destructive';
  onClick?: () => void;
}

// social props for social icon component
export interface SocialNav extends Nav {}

// agreement props for agreement component, contains privacy policy and terms of service
export interface AgreementNav extends Nav {}

// user props for user menu component
export interface UserNav extends Nav {
  show_name?: boolean;
  show_credits?: boolean;
  show_sign_out?: boolean;
}

export interface SectionItem extends NavItem {
  [key: string]: any;
}

export interface Section {
  id?: string;
  block?: string;
  label?: string;
  sr_only_title?: string;
  title?: string;
  description?: string;
  tip?: string;
  buttons?: Button[];
  icon?: string | ReactNode;
  image?: Image;
  image_invert?: Image;
  items?: SectionItem[];
  image_position?: 'left' | 'right' | 'top' | 'bottom' | 'center';
  text_align?: 'left' | 'center' | 'right';
  className?: string;
  component?: ReactNode;
  announcement?: Button;
  highlight_text?: string;
  [key: string]: any;
}

// header props for header component
export interface Header extends Section {
  id?: string;
  brand?: Brand;
  nav?: Nav;
  buttons?: Button[];
  user_nav?: UserNav;
  show_theme?: boolean;
  show_locale?: boolean;
  show_sign?: boolean;
  className?: string;
}

// footer props for footer component
export interface Footer extends Section {
  id?: string;
  brand?: Brand;
  nav?: Nav;
  copyright?: string;
  social?: SocialNav;
  agreement?: AgreementNav;
  show_theme?: boolean;
  show_locale?: boolean;
  show_built_with?: boolean;
  className?: string;
}

export interface FAQItem extends SectionItem {
  question?: string;
  answer?: string;
}

export interface FAQ extends Section {
  items?: FAQItem[];
}
